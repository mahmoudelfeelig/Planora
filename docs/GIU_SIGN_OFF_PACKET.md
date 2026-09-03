# GIU calibration sign-off packet

This packet is ready for institutional review, but it is not itself an institutional approval.

The repository-derived 2026 planning extrapolation is `paper/evidence/giu_extrapolated_planning_scenario.json`. It preserves facts observed in the local Spring 2023 timetable snapshot and labels all volume changes as sensitivity scenarios rather than current policy or enrollment forecasts.

An authorized GIU representative must review the exact artifact hash, resolve the open data fields listed in `docs/GIU_INSTITUTIONAL_VALIDATION_PROTOCOL.md`, and provide the following record before the preset can be called current or institution-approved.

| Field | Required value |
|---|---|
| Decision | approve, approve with documented exceptions, or reject |
| Effective academic term | institution-owned term identifier |
| Review or expiry date | ISO date |
| Timetable owner | name, role, date, signature or authenticated approval reference |
| Facilities owner | name, role, date, signature or authenticated approval reference |
| Academic representatives | names, departments, dates, approval references |
| Accessibility or student-services owner | name, role, date, approval reference |
| Data protection or information-security owner | name, role, date, approval reference |
| Approved artifact SHA-256 | exact canonical payload hash and file hash |
| Exceptions | IDs, owners, reasons, and expiry dates |

Repository maintainers may prepare, validate, and hash this packet. They must not fill institutional approval fields on GIU's behalf.
