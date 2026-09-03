# Institution policy portability

Planora treats an institution preset as a versioned bundle of assumptions, not as a university name switch. A preset is safe to use only when its source data, enforcement scope, and approval status are explicit.

## Why a single universal preset is unsafe

Official university policies use similar concepts with materially different scopes and thresholds.

- [UC Davis scheduling policy](https://registrar.ucdavis.edu/faculty-staff/academic-classroom-scheduling/scheduling-policies), last checked 2026-08-11, requires 35% of qualifying general-assignment sections outside prime time for academic year 2026–2027. It calculates compliance by subject code, exempts subject codes with fewer than ten sections, applies specific hybrid and nonphysical-section exclusions, requires standard meeting patterns during prime time, treats published capacity as a hard safety limit, and targets at least 80% room fill except for sections of 12 or fewer students.
- [UC Berkeley scheduling policy](https://registrar.berkeley.edu/faculty-staff-resources/aacademic-classroom-scheduling/academic-scheduling-policies/), last checked 2026-08-11, uses standard time blocks and a 70/30 prime-time policy calculated by scheduler cluster rather than subject. It distinguishes priority and manual phases and applies separate rules to general-assignment and department-controlled rooms.
- [University of Michigan class and classroom policy](https://provost.umich.edu/wp-content/uploads/2022/06/ClassClassroomSchedulingPolicy.pdf), document dated March 2018 and checked 2026-08-11, defines two time bands capped at 35%, at least 30% before 10 a.m. or after 4 p.m., at least 15% on Friday, a 65% seat-utilization target, hour/half-hour starts, historical-enrollment planning, phase-specific scheduling authority, life-safety restrictions, and room technology/layout requirements.
- [UniTime's university course timetabling description](https://www.unitime.org/uct_description.php), checked 2026-08-11, demonstrates that institutional systems also need class hierarchies, instructor and student conflicts, distribution preferences, room features, travel, and staged operational workflows.

These policies cannot be represented faithfully by changing one prime-time percentage. A portable policy rule needs, at minimum:

- a stable rule identifier and source/version;
- affected activities and rooms, including physical/online and ownership filters;
- aggregation scope such as subject, department, scheduler cluster, school, or campus;
- a time/day window and whether classification uses start time or interval overlap;
- a threshold, exemption, priority, or penalty;
- hard, soft, diagnostic-only, or workflow enforcement;
- required source fields and missing-data behavior;
- an approval owner and effective period.

## Current Planora mapping

| Policy concept | Representation | Current behavior |
|---|---|---|
| Room capacity and room type | room capacity/type plus activity demand/type | Exact hard enforcement, or explicit soft overflow for formats such as ITC-2007. |
| Room availability | per-room day/slot domains | Exact hard enforcement when enabled; an absent domain means unrestricted and is reported as an evidence warning. |
| Calendar and closures | `calendar_rules` and `room_closures` | Exact filtering when enabled; enabling a rule without data is a readiness blocker. |
| Travel | campus/building fields and `travel_time_rules` | Exact staff/group buffer enforcement when enabled and location data is complete. |
| Standard starts | `standard_start_slots` | Exact solver, local-search, and validator enforcement. |
| General distribution rules | typed `distribution_constraints` | Shared exact validation and CP compilation for supported hard types; unsupported hard types fail explicitly. |
| Enrollment uncertainty | nominal, scenario quantile/worst case, or budgeted deviation | One canonical demand calculation is used by room domains, exact/greedy rooming, validation, and metrics. Missing forecasts are exposed by readiness checks. |
| Prime-time share | `institutional_policy.prime_time` | Portable reporting only. It is not currently a hard or optimized scoped quota. |
| Minimum room fill | `institutional_policy.room_target_fill` | Portable reporting only. It is not currently a hard lower bound. |
| Freeze/approval phases | policy metadata and application audit workflow | Workflow evidence, not a mathematical constraint. |
| Subject/cluster exemptions, hybrid-pair counting, accommodation priority, life-safety designation | no complete canonical fields yet | Must be imported as explicit constraints/metadata or listed as a gap; presets must not imply enforcement. |

The machine-readable preflight is `services.institution_policy_readiness_service.evaluate_institution_policy_readiness`. It distinguishes a configured solver flag from the evidence needed to make that flag meaningful. Its result is included in portable research metrics and reports separate `research_semantics_ready` and `institutional_use_ready` decisions.

## Porting workflow

Start from `generic_research_university`, not from another named university. Import the local calendar, rooms, locations, capacities, features, staff availability, student demand, and distribution rules. Encode only policy values that have a dated authoritative source. Run the readiness preflight and resolve every `missing` or `unsupported` semantic check. Validate the resulting schedule independently, then obtain institutional sign-off and attach its artifact before setting `institution_approved=true`.

The GIU preset follows the same rule. It is partially calibrated to one historical Spring 2023 Berlin timetable snapshot and deliberately leaves current policy, staff, capacity, location, and demand questions open. See `paper/evidence/giu_ss23_calibration.json` and `docs/GIU_INSTITUTIONAL_VALIDATION_PROTOCOL.md`.
