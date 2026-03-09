# Planora Architecture

## Layers

### Product Layer

The product layer owns versioned scenario definitions, product metadata, feature flags, and high-level calendar/resource configuration.

Primary modules:
- `product/model.py`
- `product/migrations.py`
- `product/flags.py`
- `product/rules.py`
- `product/branding.py`

### Compiler Layer

The compiler layer lowers a `ProductScenario` into the current solver `Instance` model without forcing the solver to understand product-facing concerns directly.

Primary module:
- `product/compiler.py`

### Service Layer

The service layer exposes stable request/result contracts for scenario compilation, solve/improve, comparison, and export operations. UI and future API surfaces should target this layer instead of calling solver internals directly.

Primary modules:
- `services/contracts.py`
- `services/scenario_service.py`
- `services/solver_service.py`
- `services/compare_service.py`
- `services/export_service.py`
- `services/project_service.py`

### Solver Layer

The solver layer stays focused on performance-sensitive scheduling logic.

Primary modules:
- `core/solver_cp_sat.py`
- `core/metaheuristics.py`
- `core/engine_cli.py`

### UI Layer

The UI layer should orchestrate user interaction and render state, but avoid owning business rules or serialization contracts.

Primary modules:
- `ui/window.py`
- `ui/dialogs.py`
- `ui/app.py`

## Current Direction

Planora is being productized as a general-purpose academic scheduling system first, not a fully generic universal scheduler. The new product/compiler/service split is intended to let the backend grow without forcing large disruptive rewrites of the solver core.

Current productization additions already in place:
- versioned product scenarios and versioned legacy project payloads,
- service-backed project save/load/export/compare flows,
- named import/export template registry per institution,
- SQLite-backed project persistence alongside JSON/PKL snapshots,
- release-candidate / protected-baseline / named-branch workspace workflows,
- local workspace change history with operator attribution,
- custom calendar dimensions and named term blocks for custom generation,
- room campus/building/floor/features metadata,
- generic resource modeling beyond room/staff/group/course,
- institution templates for branding + rules + import defaults,
- connector exports for SIS / ERP / LMS interoperability,
- REST/GraphQL-style integration entrypoints plus calendar sync bundle generation,
- optional local/http backend-client split for future frontend separation,
- bulk-edit admin actions over multi-cell timetable selections.
