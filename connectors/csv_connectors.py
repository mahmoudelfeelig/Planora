from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List


class SISCsvConnector:
    def export_courses(self, inst, path: str | Path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["course_id", "code", "name", "programs"])
            writer.writeheader()
            for course in inst.courses.values():
                programs = [
                    program.name
                    for program in inst.programs.values()
                    if int(course.id) in set(int(c) for c in program.course_ids)
                ]
                writer.writerow(
                    {
                        "course_id": int(course.id),
                        "code": str(course.code),
                        "name": str(course.name),
                        "programs": ";".join(programs),
                    }
                )


class ERPCsvConnector:
    def export_staff_ownership(self, inst, path: str | Path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["staff_id", "name", "role", "course_ids"])
            writer.writeheader()
            for staff in inst.staff.values():
                writer.writerow(
                    {
                        "staff_id": int(staff.id),
                        "name": str(staff.name),
                        "role": "PROF" if staff.is_prof else "TA",
                        "course_ids": ";".join(
                            str(int(c_id)) for c_id in sorted(staff.can_teach_courses)
                        ),
                    }
                )


class LMSCsvConnector:
    def export_group_enrollments(self, inst, path: str | Path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["group_id", "group_name", "program", "course_ids"],
            )
            writer.writeheader()
            for group in inst.groups.values():
                program = inst.programs.get(int(group.program_id))
                writer.writerow(
                    {
                        "group_id": int(group.id),
                        "group_name": str(group.name),
                        "program": str(program.name) if program is not None else "",
                        "course_ids": ";".join(str(int(c_id)) for c_id in group.course_ids),
                    }
                )


def available_connectors() -> List[Dict[str, Any]]:
    return [
        {"id": "sis_csv", "label": "SIS CSV", "kind": "SIS"},
        {"id": "erp_csv", "label": "ERP CSV", "kind": "ERP"},
        {"id": "lms_csv", "label": "LMS CSV", "kind": "LMS"},
    ]
