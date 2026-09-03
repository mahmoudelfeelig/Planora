# GIU Institutional Calibration and Validation Protocol

## Status and intended use

This protocol converts the repository's historical GIU Berlin Spring 2023 timetable snapshot into a current, institution-approved Planora preset. The checked-in `giu_target` preset is not that final preset. It is a historical research configuration with an explicit evidence boundary.

The Spring 2023 document directly supports only the displayed calendar grid and the strings and assignments visible in that document. It does not establish current policy, physical room inventory, room capacities, staff rules, enrollment demand, or stakeholder objective weights.

The reproducible starting evidence is recorded in `paper/evidence/giu_ss23_calibration.json`. Every validation cycle must preserve source hashes, answer provenance, reviewer identity, approval date, effective term, and expiry or review date.

## Required institutional participants

| Role | Required authority or knowledge | Required sign-off |
|---|---|---|
| Timetable owner or registrar | authoritative calendar, course, section, and conflict policy | model semantics and final preset |
| Facilities or room-data owner | room identities, capacities, types, closures, accessibility, buildings, travel | room and travel model |
| Academic department representatives | contact hours, sharing, precedence, staff qualification, exceptions | department mappings and exceptions |
| HR or teaching-load owner | staff availability, contracts, workload caps, qualifications | staff constraints |
| Student services or accessibility representative | student conflicts, accommodations, access and fairness requirements | sectioning and fairness criteria |
| Data protection or information-security representative | lawful purpose, minimization, retention, access, and export controls | data-governance plan |
| Planora technical owner | converter, validator, experiment provenance, rollback | implementation evidence |

One person may fill multiple roles only when the institution confirms that authority in writing. Repository maintainers cannot self-approve institutional facts.

## Evidence package to request

- Current academic calendar with week identifiers, holidays, examination periods, closures, and effective term.
- Canonical course, configuration, subpart, class, cohort, and cross-listing identifiers.
- Required contact hours, duration choices, parent-child relationships, precedence, repeat patterns, and allowed time domains.
- Authoritative room inventory with stable IDs, capacity definition, room type, equipment, accessibility, building, availability, and planned closures.
- Directed travel-time matrix or an approved rule for deriving it.
- Staff IDs or privacy-preserving stable pseudonyms, qualifications, availability, workload rules, contract exceptions, and team-teaching semantics.
- Student course requests or approved aggregates, section choices, accommodations, and late-registration behavior.
- Historical final timetables plus change logs and accepted exception records for replay testing.
- The institution's definitions and priorities for prime time, fairness, free days, gaps, room utilization, schedule stability, robustness, and acceptable solve time.
- Data dictionary, retention schedule, access policy, export policy, and approval to use each dataset for research and/or operations.

Every file must have an owner, extraction date, effective term, schema version, checksum, and classification. Screenshots or prose answers may clarify policy but must not silently replace canonical machine-readable data.

## Validation questionnaire

### Calendar and time grid

- What term and campus does this configuration govern, and when does it expire?
- Which days can teaching occur? Are Saturdays, Sundays, evenings, intensive blocks, and make-up days allowed?
- What are the exact start times, durations, passing periods, and cross-midnight rules?
- Are displayed timetable starts the only permitted starts, preferred starts, or merely historical usage?
- How are holidays, partial closures, reading weeks, examinations, and one-off exceptions represented?
- Can a class meet on different days, weeks, times, or durations during one term?

### Courses, sections, and cohorts

- Which IDs are stable across source systems?
- Which configurations are alternatives, and which subparts must a student select together?
- How are parent-child sections, cross-listed courses, shared lectures, and linked practicals represented?
- Which conflicts are hard, which are waivable, and who can authorize a waiver?
- Are contact-hour totals exact, minimum, maximum, or target values?
- Which activities require consecutive slots, gaps, precedence, repeated rooms, or repeated weekly patterns?

### Rooms, buildings, and accessibility

- Does capacity mean seats, examination capacity, fire-code occupancy, or usable capacity for a class type?
- Which room types and equipment are hard requirements versus preferences?
- Are combined or partitioned rooms represented as one resource, several resources, or mutually exclusive configurations?
- Which room labels in the historical PDF are aliases, compound assignments, virtual locations, or extraction errors?
- What closures and availability intervals are authoritative?
- What travel times apply by direction, mode, accessibility need, time of day, and passing-period policy?

### Staff and teaching load

- Which person teaches each activity, and how are teams, substitutes, and vacancies modeled?
- What daily, weekly, consecutive-teaching, break, travel, and campus-switch limits apply?
- Which qualifications and course ownership constraints are hard?
- How are part-time contracts, research days, preferences, exceptions, and workload balancing represented?
- May staff identifiers be used in research artifacts, or must they be pseudonymized or aggregated?

### Students, demand, and sectioning

- Are individual course requests available, and at what point are they reliable?
- Which accommodations create hard time, room, travel, or capacity requirements?
- Are class limits strict, reservable by cohort, or adjustable with approval?
- Which conflicts count in the student objective, including overlap, insufficient travel, or back-to-back load?
- How should alternative configurations and parent-child sections be selected?
- What forecast history supports nominal, quantile, scenario, or budgeted demand, and how is its service level approved?

### Objectives, fairness, and stability

- Who is the affected stakeholder for each objective, and what unit is being minimized?
- What is the approved priority order or trade-off between feasibility, student conflicts, staff burden, cohort burden, room utilization, stability, and robustness?
- What is the institution's prime-time definition and allocation cap, if any?
- Which fairness statistic is acceptable, and what disparity threshold triggers review?
- How much change from the published timetable is acceptable during repair?
- Which objective values must be reported separately rather than collapsed into one score?

### Exceptions and governance

- Who can approve an exception, what reason code is required, and when does it expire?
- Which records contain personal or sensitive data, and who may access raw versus aggregated forms?
- What is the retention and deletion policy for source data, solver logs, schedules, and research exports?
- What audit trail must be retained for model changes, manual overrides, and published schedules?
- What incident, rollback, and correction process applies when an invalid schedule is discovered?

## Calibration workflow

### Provenance lock

Copy approved inputs into the controlled calibration environment. Record cryptographic hashes, schemas, owners, effective dates, extraction queries, row counts, and access classification. Never overwrite a source snapshot; create a new calibration version.

### Semantic mapping

Map every institutional field to the Planora canonical model. For each field record whether it is confirmed, transformed, inferred, defaulted, intentionally omitted, or unsupported. Unknown values must remain unknown; they must not become large capacities, unrestricted availability, or synthetic institutional facts.

### Constraint review

Produce a human-readable constraint catalogue. The institutional owner must review each hard constraint, exception path, soft penalty, objective priority, and unit. Safe generic invariants such as preventing double booking still require valid source data for the resources they protect.

### Data-quality checks

Check identifier uniqueness, referential integrity, missingness, duplicate records, capacity definitions, time-domain validity, hierarchy cycles, unexplained overlaps, cross-list aliases, and calendar coverage. Resolve or explicitly waive every anomaly. A waived source anomaly remains visible in the calibration report.

### Historical replay

Import at least one institution-approved historical term and validate it against an independent institutional or official validator. Explain every mismatch. Replaying a published schedule is evidence of semantic agreement, not evidence that the optimization objective is correct or that a better schedule is acceptable.

### Controlled solve and sensitivity analysis

Run deterministic feasibility checks, then multi-seed optimization experiments. Vary uncertain capacities, enrollment demand, prime-time definitions, objective weights, and fairness thresholds. Report feasibility, optimality gap or bound status, validation agreement, runtime, memory, and stakeholder-level effects separately.

### User acceptance and sign-off

Administrators review the wizard-generated configuration, representative schedules, conflicts, certificates, and manual-override behavior. Required owners sign the exact preset hash and calibration artifact hash. Record effective term and review date.

## Acceptance gates

| Gate | Pass condition |
|---|---|
| Source provenance | all required inputs have owner, effective term, schema, hash, and approved use |
| Semantic coverage | every required canonical field is confirmed or explicitly unsupported; no silent synthetic facts |
| Data quality | all blocking missingness, reference errors, aliases, and overlaps are resolved or formally waived |
| Independent validation | exported schedules agree with the approved independent validator on all hard constraints and reported objective components |
| Historical replay | approved historical schedule imports and validates with every mismatch adjudicated |
| Objective calibration | stakeholder owners approve definitions, units, priorities, thresholds, and sensitivity results |
| Operational acceptance | administrator workflow, access control, audit log, override, rollback, and recovery tests pass |
| Governance | privacy, retention, access, export, and research-publication uses are approved |
| Currency | preset effective term and review/expiry date are present and have not elapsed |
| Sign-off | required owners approve the exact preset and evidence hashes |

Failure of any gate keeps the preset in `historical_partial_calibration` or `institutional_validation_pending` status. It must not be described as official, current, production-calibrated, or institution-approved.

## Required signed output

The approved calibration record must contain:

- preset ID, semantic version, effective term, review date, and status;
- canonical JSON payload and SHA-256 hash;
- source manifest and hashes;
- field-level evidence classifications and unresolved limitations;
- independent-validator identity, version, command or procedure, and agreement report;
- historical replay and sensitivity evidence;
- names, roles, dates, and decisions for every required approver;
- rollback target and change log from the previous approved version.

Any later source, policy, schema, or objective change invalidates the prior hash and starts a new validation cycle.
