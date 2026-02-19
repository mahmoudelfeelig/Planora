from __future__ import annotations

from typing import Dict, Any, List, Tuple

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
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


class MoveConflictDialog(QDialog):
    def __init__(
        self,
        parent,
        inst: Instance,
        schedule: Dict[int, Dict[str, Any]],
        held_activity_id: int,
        target_day: str,
        target_slot: int,
        conflicts: List[Dict[str, Any]],
        relocation_options: Dict[int, List[Tuple[str, int]]],
    ):
        super().__init__(parent)
        self.inst = inst
        self.schedule = schedule
        self.held_activity_id = int(held_activity_id)
        self.target_day = str(target_day)
        self.target_slot = int(target_slot)
        self.conflicts = conflicts
        self.relocation_options = relocation_options
        self._decision: Tuple | None = None

        self.setWindowTitle("Resolve move conflicts")
        root = QVBoxLayout(self)

        intro = QLabel(
            f"Moving A{self.held_activity_id} to {self.target_day} S{self.target_slot + 1} "
            "creates conflicts. Choose a conflict activity to resolve."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.conflict_table = QTableWidget(len(conflicts), 5)
        self.conflict_table.setHorizontalHeaderLabels(
            ["Activity", "Conflict", "Current time", "Room", "Staff"]
        )
        self.conflict_table.verticalHeader().setVisible(False)
        for row, conflict in enumerate(conflicts):
            b_id = int(conflict["activity_id"])
            info = schedule[b_id]
            course = inst.courses.get(info["course_id"])
            room = inst.rooms.get(info["room_id"])
            staff = inst.staff.get(info["staff_id"])
            title = f"A{b_id}"
            if course is not None:
                title += f" {course.code}"
            reasons = ", ".join(conflict.get("reasons", [])) or "overlap"
            self.conflict_table.setItem(row, 0, QTableWidgetItem(title))
            self.conflict_table.setItem(row, 1, QTableWidgetItem(reasons))
            self.conflict_table.setItem(
                row, 2, QTableWidgetItem(f"{info['day']} S{int(info['slot']) + 1}")
            )
            self.conflict_table.setItem(
                row, 3, QTableWidgetItem(room.name if room is not None else "-")
            )
            self.conflict_table.setItem(
                row, 4, QTableWidgetItem(staff.name if staff is not None else "-")
            )
        self.conflict_table.resizeColumnsToContents()
        root.addWidget(self.conflict_table)

        form = QFormLayout()
        self.conflict_combo = QComboBox()
        for conflict in conflicts:
            b_id = int(conflict["activity_id"])
            info = schedule[b_id]
            course = inst.courses.get(info["course_id"])
            label = f"A{b_id}"
            if course is not None:
                label += f" {course.code}"
            label += f" ({info['day']} S{int(info['slot']) + 1})"
            self.conflict_combo.addItem(label, b_id)
        form.addRow("Conflict activity:", self.conflict_combo)

        self.relocate_combo = QComboBox()
        form.addRow("Relocate to:", self.relocate_combo)
        root.addLayout(form)

        actions = QHBoxLayout()
        self.swap_btn = QPushButton("Swap timeslots")
        self.move_btn = QPushButton("Move conflict away")
        self.cancel_btn = QPushButton("Cancel")
        actions.addWidget(self.swap_btn)
        actions.addWidget(self.move_btn)
        actions.addWidget(self.cancel_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self.conflict_combo.currentIndexChanged.connect(self._refresh_relocation_options)
        self.swap_btn.clicked.connect(self._on_swap)
        self.move_btn.clicked.connect(self._on_move)
        self.cancel_btn.clicked.connect(self.reject)
        self._refresh_relocation_options()

    def _refresh_relocation_options(self) -> None:
        self.relocate_combo.clear()
        b_id = self.conflict_combo.currentData()
        if b_id is None:
            self.swap_btn.setEnabled(False)
            self.move_btn.setEnabled(False)
            return
        options = self.relocation_options.get(int(b_id), [])
        for day, slot in options:
            self.relocate_combo.addItem(f"{day} S{int(slot) + 1}", (str(day), int(slot)))
        self.swap_btn.setEnabled(True)
        self.move_btn.setEnabled(bool(options))

    def _on_swap(self) -> None:
        b_id = self.conflict_combo.currentData()
        if b_id is None:
            return
        self._decision = ("swap", int(b_id))
        self.accept()

    def _on_move(self) -> None:
        b_id = self.conflict_combo.currentData()
        relocation = self.relocate_combo.currentData()
        if b_id is None or relocation is None:
            return
        day, slot = relocation
        self._decision = ("relocate", int(b_id), str(day), int(slot))
        self.accept()

    def get_decision(self) -> Tuple | None:
        return self._decision


class ConflictInspectorDialog(QDialog):
    def __init__(self, parent, errors: List[str]):
        super().__init__(parent)
        self.errors = list(errors)
        self._selected_activity_id: int | None = None
        self.setWindowTitle("Conflict Inspector")

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Hard-constraint conflicts detected. Select a row and jump to its activity."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(len(self.errors), 2)
        self.table.setHorizontalHeaderLabels(["Activity", "Message"])
        self.table.verticalHeader().setVisible(False)
        for row, message in enumerate(self.errors):
            activity_id = self._extract_activity_id(message)
            a_text = f"A{activity_id}" if activity_id is not None else "-"
            self.table.setItem(row, 0, QTableWidgetItem(a_text))
            self.table.setItem(row, 1, QTableWidgetItem(str(message)))
            if activity_id is not None:
                self.table.item(row, 0).setData(0x0100, int(activity_id))
                self.table.item(row, 1).setData(0x0100, int(activity_id))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)

        actions = QHBoxLayout()
        self.jump_btn = QPushButton("Jump To Activity")
        self.close_btn = QPushButton("Close")
        actions.addWidget(self.jump_btn)
        actions.addWidget(self.close_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.jump_btn.clicked.connect(self._on_jump)
        self.close_btn.clicked.connect(self.reject)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)

    @staticmethod
    def _extract_activity_id(message: str) -> int | None:
        msg = str(message)
        idx = msg.find("A")
        if idx < 0:
            return None
        digits: List[str] = []
        for ch in msg[idx + 1 :]:
            if ch.isdigit():
                digits.append(ch)
            else:
                break
        if not digits:
            return None
        try:
            return int("".join(digits))
        except Exception:
            return None

    def _resolve_selected_activity(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        for col in (0, 1):
            item = self.table.item(row, col)
            if item is None:
                continue
            data = item.data(0x0100)
            if data is None:
                continue
            try:
                return int(data)
            except Exception:
                continue
        return None

    def _on_jump(self) -> None:
        activity_id = self._resolve_selected_activity()
        if activity_id is None:
            return
        self._selected_activity_id = int(activity_id)
        self.accept()

    def _on_cell_double_clicked(self, _row: int, _col: int) -> None:
        self._on_jump()

    def selected_activity_id(self) -> int | None:
        return self._selected_activity_id
