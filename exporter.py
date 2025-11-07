from __future__ import annotations
from typing import Dict, Any
from docx import Document
from docx.shared import Pt

from domain import Instance

TIME_LABELS = [
    "08:30 - 10:00",
    "10:30 - 12:00",
    "12:15 - 13:45",
    "14:15 - 15:45",
    "16:00 - 17:30",
]


def export_group_schedules_to_docx(inst: Instance,
                                   schedule: Dict[int, Dict[str, Any]],
                                   filename: str) -> None:
    doc = Document()
    days = inst.days
    slots = inst.slots_per_day
    slot_labels = TIME_LABELS[:slots] if len(TIME_LABELS) >= slots else [
        f"Slot {i + 1}" for i in range(slots)
    ]

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    group_ids = sorted(inst.groups.keys())
    first_page = True

    for g_id in group_ids:
        group = inst.groups[g_id]
        program = inst.programs.get(group.program_id)

        for w in inst.weeks:
            if not first_page:
                doc.add_page_break()
            first_page = False

            heading_text = f"{program.name if program else 'Program'} - {group.name} - Week {w}"
            doc.add_heading(heading_text, level=1)

            table = doc.add_table(rows=len(days) + 1, cols=slots + 1)
            table.style = "Table Grid"

            table.cell(0, 0).text = "Day / Time"
            for c in range(slots):
                table.cell(0, c + 1).text = slot_labels[c]

            for row, day in enumerate(days, start=1):
                table.cell(row, 0).text = day
                for col in range(slots):
                    cell = table.cell(row, col + 1)
                    entries = []

                    for a_id, info in schedule.items():
                        if info["week"] != w:
                            continue
                        if g_id not in info["group_ids"]:
                            continue
                        if info["day"] != day:
                            continue

                        start = info["slot"]
                        dur = info["duration"]
                        if col < start or col >= start + dur:
                            continue

                        course = inst.courses.get(info["course_id"])
                        room = inst.rooms.get(info["room_id"])
                        staff = inst.staff.get(info["staff_id"])

                        line = []
                        if course:
                            line.append(course.code)
                            line.append(course.name)
                        line.append(info["kind"])
                        if room:
                            line.append(f"Room: {room.name}")
                        if staff:
                            line.append(f"Staff: {staff.name}")

                        entries.append("\n".join(line))

                    cell.text = "\n\n".join(entries) if entries else ""

    doc.save(filename)
