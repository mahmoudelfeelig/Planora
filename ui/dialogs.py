from __future__ import annotations

from typing import Dict, Any, List, Tuple

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QCheckBox,
)

from utils.domain import Instance


class EditActivityDialog(QDialog):
    def __init__(
        self,
        parent,
        inst: Instance,
        schedule: Dict[int, Dict[str, Any]],
        act_ids: List[int],
        week: int,
        day: str,
        slot: int,
        locked: Dict[int, Dict[str, Any]] | None = None,
    ):
        super().__init__(parent)
        self.inst = inst
        self.schedule = schedule
        self.act_ids = act_ids
        self.week = week
        self.locked = locked or {}

        self.setWindowTitle("Edit activity")
        layout = QFormLayout(self)

        self.activity_combo = QComboBox()
        for a_id in act_ids:
            info = schedule[a_id]
            course = inst.courses.get(info["course_id"])
            label = f"A{a_id}"
            if course:
                label += f" {course.code} {course.name}"
            label += f" ({info['kind']})"
            self.activity_combo.addItem(label, a_id)
        layout.addRow("Activity:", self.activity_combo)

        self.day_combo = QComboBox()
        for d in inst.days:
            self.day_combo.addItem(d, d)
        idx = self.day_combo.findData(day)
        if idx >= 0:
            self.day_combo.setCurrentIndex(idx)
        layout.addRow("Day:", self.day_combo)

        self.slot_combo = QComboBox()
        for s in range(inst.slots_per_day):
            self.slot_combo.addItem(str(s + 1), s)
        idx = self.slot_combo.findData(slot)
        if idx >= 0:
            self.slot_combo.setCurrentIndex(idx)
        layout.addRow("Start slot:", self.slot_combo)

        self.room_combo = QComboBox()
        for r_id, r in inst.rooms.items():
            self.room_combo.addItem(f"{r.name} (id {r_id})", r_id)
        cur_a_id = self.activity_combo.currentData()
        cur_info = schedule[cur_a_id]
        cur_room = cur_info["room_id"]
        idx = self.room_combo.findData(cur_room)
        if idx >= 0:
            self.room_combo.setCurrentIndex(idx)
        layout.addRow("Room:", self.room_combo)

        self.staff_combo = QComboBox()
        self._populate_staff_combo(int(cur_a_id))
        layout.addRow("Staff:", self.staff_combo)

        self.lock_time_cb = QCheckBox("Lock time (day/slot)")
        self.lock_room_cb = QCheckBox("Lock room")
        fixed = self.locked.get(int(cur_a_id), {})
        if isinstance(fixed, dict):
            self.lock_time_cb.setChecked("day" in fixed and "slot" in fixed)
            self.lock_room_cb.setChecked("room_id" in fixed)
        layout.addRow(self.lock_time_cb)
        layout.addRow(self.lock_room_cb)

        self.activity_combo.currentIndexChanged.connect(self._on_activity_changed)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _populate_staff_combo(self, a_id: int) -> None:
        self.staff_combo.clear()
        act = self.inst.activities[a_id]
        course_id = act.course_id
        want_prof = act.kind == "LEC"
        for s_id, s in self.inst.staff.items():
            if want_prof and not s.is_prof:
                continue
            if (not want_prof) and s.is_prof:
                continue
            if course_id not in getattr(s, "can_teach_courses", set()):
                continue
            self.staff_combo.addItem(f"{s.name} (id {s_id})", s_id)

        cur_info = self.schedule[a_id]
        cur_staff = cur_info["staff_id"]
        idx = self.staff_combo.findData(cur_staff)
        if idx >= 0:
            self.staff_combo.setCurrentIndex(idx)

    def _on_activity_changed(self) -> None:
        a_id = int(self.activity_combo.currentData())
        info = self.schedule[a_id]

        idx = self.day_combo.findData(info["day"])
        if idx >= 0:
            self.day_combo.setCurrentIndex(idx)

        idx = self.slot_combo.findData(info["slot"])
        if idx >= 0:
            self.slot_combo.setCurrentIndex(idx)

        idx = self.room_combo.findData(info["room_id"])
        if idx >= 0:
            self.room_combo.setCurrentIndex(idx)

        self._populate_staff_combo(a_id)

        fixed = self.locked.get(a_id, {})
        if isinstance(fixed, dict):
            self.lock_time_cb.setChecked("day" in fixed and "slot" in fixed)
            self.lock_room_cb.setChecked("room_id" in fixed)
        else:
            self.lock_time_cb.setChecked(False)
            self.lock_room_cb.setChecked(False)

    def get_values(self) -> Tuple[int, str, int, int, int, bool, bool]:
        a_id = self.activity_combo.currentData()
        day = self.day_combo.currentData()
        slot = self.slot_combo.currentData()
        room_id = self.room_combo.currentData()
        staff_id = self.staff_combo.currentData()
        return a_id, day, slot, room_id, staff_id, bool(self.lock_time_cb.isChecked()), bool(self.lock_room_cb.isChecked())
