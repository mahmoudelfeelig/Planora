from __future__ import annotations

from ui.window_runtime import *  # noqa: F401,F403


class WindowGenerationMixin:

    def _ensure_custom_generator_seeded(self) -> None:
        # Keep custom tables populated even after resize/layout edge-cases.
        try:
            if hasattr(self, "custom_program_table") and self.custom_program_table.rowCount() <= 0:
                self._reset_custom_program_table()
            if hasattr(self, "custom_course_pattern_table") and self.custom_course_pattern_table.rowCount() <= 0:
                self._reset_custom_course_pattern_table()
            if hasattr(self, "custom_staff_table") and self.custom_staff_table.rowCount() <= 0:
                self._reset_custom_staff_table()
            if hasattr(self, "custom_room_table") and self.custom_room_table.rowCount() <= 0:
                self._reset_custom_room_table()
            if hasattr(self, "staff_course_picker_combo"):
                self._refresh_staff_course_picker()
            if hasattr(self, "custom_room_capacity_mode_combo"):
                self._apply_room_capacity_mode()
            self._normalize_custom_table_item_types()
        except Exception:
            traceback.print_exc()

    def _normalize_custom_table_item_types(self) -> None:
        """Ensure key sortable columns use numeric-aware item classes."""
        if hasattr(self, "custom_program_table"):
            was_sorting = self.custom_program_table.isSortingEnabled()
            self.custom_program_table.setSortingEnabled(False)
            for row in range(self.custom_program_table.rowCount()):
                item = self.custom_program_table.item(row, 0)
                txt = str(item.text()).strip() if item is not None else str(row + 1)
                self.custom_program_table.setItem(
                    row, 0, self._make_locked_item(txt, numeric=True)
                )
                name_item = self.custom_program_table.item(row, 1)
                if name_item is not None:
                    self.custom_program_table.setItem(
                        row, 1, NaturalSortTableItem(str(name_item.text()))
                    )
            self.custom_program_table.setSortingEnabled(was_sorting)
        if hasattr(self, "custom_course_pattern_table"):
            was_sorting = self.custom_course_pattern_table.isSortingEnabled()
            self.custom_course_pattern_table.setSortingEnabled(False)
            for row in range(self.custom_course_pattern_table.rowCount()):
                id_item = self.custom_course_pattern_table.item(row, 0)
                id_txt = str(id_item.text()).strip() if id_item is not None else str(row + 1)
                self.custom_course_pattern_table.setItem(
                    row, 0, self._make_locked_item(id_txt, numeric=True)
                )
                name_item = self.custom_course_pattern_table.item(row, 1)
                if name_item is not None:
                    name_txt = str(name_item.text())
                    self.custom_course_pattern_table.setItem(
                        row, 1, self._make_locked_item(name_txt, natural=True)
                    )
            self.custom_course_pattern_table.setSortingEnabled(was_sorting)
        if hasattr(self, "custom_staff_table"):
            was_sorting = self.custom_staff_table.isSortingEnabled()
            self.custom_staff_table.setSortingEnabled(False)
            for row in range(self.custom_staff_table.rowCount()):
                name_item = self.custom_staff_table.item(row, 0)
                if name_item is not None:
                    self.custom_staff_table.setItem(
                        row, 0, NaturalSortTableItem(str(name_item.text()))
                    )
            self.custom_staff_table.setSortingEnabled(was_sorting)
        if hasattr(self, "custom_room_table"):
            was_sorting = self.custom_room_table.isSortingEnabled()
            self.custom_room_table.setSortingEnabled(False)
            for row in range(self.custom_room_table.rowCount()):
                name_item = self.custom_room_table.item(row, 0)
                if name_item is not None:
                    self.custom_room_table.setItem(
                        row, 0, NaturalSortTableItem(str(name_item.text()))
                    )
            self.custom_room_table.setSortingEnabled(was_sorting)

    def _build_generator_tab(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        counts_box = QGroupBox("Scenario Size")
        counts_form = QFormLayout(counts_box)
        self.custom_programs_spin = StepSpinBox()
        self.custom_programs_spin.setRange(1, 200)
        self.custom_programs_spin.setValue(20)
        self.custom_groups_per_program_spin = StepSpinBox()
        self.custom_groups_per_program_spin.setRange(1, 20)
        self.custom_groups_per_program_spin.setValue(2)
        self.custom_group_size_spin = StepSpinBox()
        self.custom_group_size_spin.setRange(1, 2000)
        self.custom_group_size_spin.setValue(60)
        self.custom_courses_per_program_spin = StepSpinBox()
        self.custom_courses_per_program_spin.setRange(1, 20)
        self.custom_courses_per_program_spin.setValue(6)
        self.custom_slots_per_day_spin = StepSpinBox()
        self.custom_slots_per_day_spin.setRange(3, 16)
        self.custom_slots_per_day_spin.setValue(5)
        self.custom_days_edit = QLineEdit()
        self.custom_days_edit.setText("MON,TUE,WED,THU,FRI,SAT")
        self.custom_weeks_edit = QLineEdit()
        self.custom_weeks_edit.setText("1-12")
        self.custom_term_blocks_edit = QLineEdit()
        self.custom_term_blocks_edit.setPlaceholderText(
            "Optional named blocks: Teaching A:8, Exams:2, Teaching B:6"
        )
        self.custom_term_blocks_edit.setToolTip(
            "Optional arbitrary term layout. Format: Label:length_weeks, !NonTeaching:length_weeks.\n"
            "When present, this overrides the plain Teaching weeks field."
        )
        self.custom_course_names_edit = QLineEdit()
        self.custom_course_names_edit.setPlaceholderText(
            "Optional CSV names: Algorithms,Databases,Networks,..."
        )
        counts_form.addRow("Programs", self.custom_programs_spin)
        counts_form.addRow("Groups per program", self.custom_groups_per_program_spin)
        counts_form.addRow("Students per group", self.custom_group_size_spin)
        counts_form.addRow("Courses per program", self.custom_courses_per_program_spin)
        counts_form.addRow("Slots per day", self.custom_slots_per_day_spin)
        counts_form.addRow("Teaching days (CSV)", self.custom_days_edit)
        counts_form.addRow("Teaching weeks", self.custom_weeks_edit)
        counts_form.addRow("Term blocks", self.custom_term_blocks_edit)
        counts_form.addRow("Course names (CSV)", self.custom_course_names_edit)
        cfg_row = QWidget()
        cfg_row_layout = QHBoxLayout(cfg_row)
        cfg_row_layout.setContentsMargins(0, 0, 0, 0)
        cfg_row_layout.setSpacing(6)
        self.custom_save_local_btn = QPushButton("Save Local")
        self.custom_save_cfg_btn = QPushButton("Save Config...")
        self.custom_load_cfg_btn = QPushButton("Load Config...")
        cfg_row_layout.addWidget(self.custom_save_local_btn)
        cfg_row_layout.addWidget(self.custom_save_cfg_btn)
        cfg_row_layout.addWidget(self.custom_load_cfg_btn)
        cfg_row_layout.addStretch(1)
        counts_form.addRow("Custom config", cfg_row)
        layout.addWidget(
            self._build_collapsible_section("Scenario Size", counts_box, collapsed=True)
        )

        plan_box = QGroupBox("Program/Course Overrides")
        plan_layout = QVBoxLayout(plan_box)
        plan_controls = QHBoxLayout()
        self.custom_reset_programs_btn = QPushButton("Reset Program Rows")
        self.custom_reset_course_patterns_btn = QPushButton("Reset Course Patterns")
        plan_controls.addWidget(self.custom_reset_programs_btn)
        plan_controls.addWidget(self.custom_reset_course_patterns_btn)
        plan_controls.addStretch(1)
        plan_layout.addLayout(plan_controls)

        self.custom_program_table = QTableWidget(0, 6)
        self.custom_program_table.setHorizontalHeaderLabels(
            ["Program ID", "Program Name", "Groups", "Group Size", "Courses", "Courses/Group"]
        )
        self.custom_program_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.custom_program_table.verticalHeader().setVisible(False)
        self.custom_program_table.setSortingEnabled(True)
        self.custom_program_table.setMinimumHeight(220)
        self.custom_program_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plan_layout.addWidget(self.custom_program_table)

        self.custom_course_pattern_table = QTableWidget(0, 8)
        self.custom_course_pattern_table.setHorizontalHeaderLabels(
            [
                "Course ID",
                "Course Name",
                "LEC Count",
                "TUT Count",
                "Lab Count",
                "Lab Type",
                "Lab Dur",
                "Lab Tag",
            ]
        )
        self.custom_course_pattern_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.custom_course_pattern_table.verticalHeader().setVisible(False)
        self.custom_course_pattern_table.setSortingEnabled(True)
        self.custom_course_pattern_table.setMinimumHeight(300)
        self.custom_course_pattern_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        plan_layout.addWidget(self.custom_course_pattern_table)

        plan_hint = QLabel(
            "Program rows allow different groups/courses per program and courses per group.\n"
            "Course pattern rows allow per-course LEC/TUT/LAB totals and lab type (NONE/NORMAL/SPECIAL).\n"
            "Course structure is inferred from counts (e.g., lab-only, lec-only, tut-only)."
        )
        plan_hint.setWordWrap(True)
        plan_layout.addWidget(plan_hint)
        layout.addWidget(
            self._build_collapsible_section(
                "Program/Course Overrides", plan_box, collapsed=True
            )
        )

        staff_box = QGroupBox("Staff Mapping")
        staff_layout = QVBoxLayout(staff_box)
        staff_controls = QHBoxLayout()
        self.custom_num_profs_spin = StepSpinBox()
        self.custom_num_profs_spin.setRange(1, 500)
        self.custom_num_profs_spin.setValue(40)
        self.custom_num_tas_spin = StepSpinBox()
        self.custom_num_tas_spin.setRange(1, 500)
        self.custom_num_tas_spin.setValue(30)
        self.custom_reset_staff_btn = QPushButton("Reset Staff Rows")
        staff_controls.addWidget(QLabel("Professors"))
        staff_controls.addWidget(self.custom_num_profs_spin)
        staff_controls.addWidget(QLabel("TAs"))
        staff_controls.addWidget(self.custom_num_tas_spin)
        staff_controls.addWidget(self.custom_reset_staff_btn)
        self.staff_course_picker_combo = QComboBox()
        self.staff_course_picker_combo.setMinimumWidth(200)
        self.staff_add_course_btn = QPushButton("Add Course To Selected Staff")
        self.staff_add_course_btn.setMinimumWidth(180)
        staff_controls.addWidget(QLabel("Course ID picker"))
        staff_controls.addWidget(self.staff_course_picker_combo)
        staff_controls.addWidget(self.staff_add_course_btn)
        staff_controls.addStretch(1)
        staff_layout.addLayout(staff_controls)
        self.custom_staff_table = QTableWidget(0, 5)
        self.custom_staff_table.setHorizontalHeaderLabels(
            [
                "Staff",
                "Role",
                "Course IDs (csv)",
                "Available Days (csv)",
                "Available Weeks (csv or ALL)",
            ]
        )
        self.custom_staff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.custom_staff_table.horizontalHeader().setSectionsClickable(True)
        self.custom_staff_table.horizontalHeader().setSortIndicatorShown(True)
        self.custom_staff_table.verticalHeader().setVisible(False)
        self.custom_staff_table.setSortingEnabled(True)
        self.custom_staff_table.setMinimumHeight(360)
        self.custom_staff_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        staff_layout.addWidget(self.custom_staff_table)
        layout.addWidget(
            self._build_collapsible_section("Staff Mapping", staff_box, collapsed=True)
        )

        room_box = QGroupBox("Room Definitions")
        room_layout = QVBoxLayout(room_box)
        room_controls = QHBoxLayout()
        self.custom_room_count_spin = StepSpinBox()
        self.custom_room_count_spin.setRange(1, 500)
        self.custom_room_count_spin.setValue(30)
        self.custom_reset_rooms_btn = QPushButton("Reset Room Rows")
        room_controls.addWidget(QLabel("Total rooms"))
        room_controls.addWidget(self.custom_room_count_spin)
        room_controls.addWidget(self.custom_reset_rooms_btn)
        room_controls.addWidget(QLabel("Capacity mode"))
        self.custom_room_capacity_mode_combo = QComboBox()
        for label, mode in ROOM_CAPACITY_MODE_CHOICES:
            self.custom_room_capacity_mode_combo.addItem(str(label), str(mode))
        numeric_idx = self.custom_room_capacity_mode_combo.findData("numeric")
        if numeric_idx >= 0:
            self.custom_room_capacity_mode_combo.setCurrentIndex(numeric_idx)
        room_controls.addWidget(self.custom_room_capacity_mode_combo)
        room_controls.addStretch(1)
        room_layout.addLayout(room_controls)
        self.custom_room_table = QTableWidget(0, 9)
        self.custom_room_table.setHorizontalHeaderLabels(
            [
                "Name",
                "Type",
                "Category",
                "Capacity",
                "Campus",
                "Building",
                "Floor",
                "Features (csv)",
                "Tags (csv for specialized labs)",
            ]
        )
        self.custom_room_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.custom_room_table.horizontalHeader().setSectionsClickable(True)
        self.custom_room_table.horizontalHeader().setSortIndicatorShown(True)
        self.custom_room_table.verticalHeader().setVisible(False)
        self.custom_room_table.setSortingEnabled(True)
        self.custom_room_table.setMinimumHeight(280)
        self.custom_room_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        room_layout.addWidget(self.custom_room_table)
        layout.addWidget(
            self._build_collapsible_section("Room Definitions", room_box, collapsed=True)
        )

        hint = QLabel(
            "Use mode 'custom' to generate from these tables.\n"
            "Room capacity mode controls whether category labels or exact capacities are authoritative."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return scroll

    def _find_room_combo_position(self, combo: QComboBox) -> Tuple[int, int]:
        for row in range(self.custom_room_table.rowCount()):
            for col in (1, 2):
                if self.custom_room_table.cellWidget(row, col) is combo:
                    return row, col
        return -1, -1

    def _on_room_combo_changed(self, _text: str) -> None:
        if self._room_table_internal_change:
            return
        sender = self.sender()
        if not isinstance(sender, QComboBox):
            return
        row, col = self._find_room_combo_position(sender)
        if row < 0 or col < 0:
            return
        item = self.custom_room_table.item(row, col)
        if item is None:
            item = self._make_locked_item(sender.currentText())
            self.custom_room_table.setItem(row, col, item)
        else:
            item.setText(sender.currentText())
        self._on_room_table_item_changed(item)

    def _set_room_enum_cell(
        self,
        row: int,
        col: int,
        *,
        options: Tuple[str, ...],
        value: str,
    ) -> None:
        value_norm = str(value).strip().upper()
        if value_norm not in options:
            value_norm = options[0]
        self.custom_room_table.setItem(row, col, self._make_locked_item(value_norm))
        combo = QComboBox(self.custom_room_table)
        combo.addItems(list(options))
        combo.blockSignals(True)
        idx = combo.findText(value_norm)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        combo.currentTextChanged.connect(self._on_room_combo_changed)
        self.custom_room_table.setCellWidget(row, col, combo)

    def _room_table_text(self, row: int, col: int) -> str:
        widget = self.custom_room_table.cellWidget(row, col)
        if isinstance(widget, QComboBox):
            return str(widget.currentText()).strip()
        item = self.custom_room_table.item(row, col)
        return str(item.text()).strip() if item is not None else ""

    def _room_capacity_mode(self) -> str:
        if not hasattr(self, "custom_room_capacity_mode_combo"):
            return "numeric"
        data = self.custom_room_capacity_mode_combo.currentData()
        mode = str(data if data is not None else self.custom_room_capacity_mode_combo.currentText()).strip().lower()
        return "categorical" if mode.startswith("cat") else "numeric"

    def _on_room_capacity_mode_changed(self, _index: int) -> None:
        self._apply_room_capacity_mode()
        # Re-normalize room rows to the active authority (category or numeric).
        for row in range(self.custom_room_table.rowCount()):
            cap_item = self.custom_room_table.item(row, 3)
            if cap_item is not None:
                self._on_room_table_item_changed(cap_item)

    def _apply_room_capacity_mode(self) -> None:
        mode = self._room_capacity_mode()
        for row in range(self.custom_room_table.rowCount()):
            cap_item = self.custom_room_table.item(row, 3)
            if cap_item is not None:
                if mode == "categorical":
                    cap_item.setFlags(cap_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                else:
                    cap_item.setFlags(cap_item.flags() | Qt.ItemFlag.ItemIsEditable)
            cat_combo = self.custom_room_table.cellWidget(row, 2)
            if isinstance(cat_combo, QComboBox):
                cat_combo.setEnabled(mode == "categorical")

    def _reset_custom_staff_table(self) -> None:
        rows = int(self.custom_num_profs_spin.value()) + int(self.custom_num_tas_spin.value())
        default_days = self._parse_csv_days(
            self.custom_days_edit.text() if hasattr(self, "custom_days_edit") else ""
        ) or (self.inst.days if self.inst else ["MON", "TUE", "WED", "THU", "FRI", "SAT"])
        default_days_text = ",".join(default_days)
        was_sorting = self.custom_staff_table.isSortingEnabled()
        self.custom_staff_table.setSortingEnabled(False)
        self.custom_staff_table.blockSignals(True)
        self.custom_staff_table.setRowCount(rows)
        row = 0
        for idx in range(1, int(self.custom_num_profs_spin.value()) + 1):
            name_item = NaturalSortTableItem(f"Prof-{idx}")
            role_item = QTableWidgetItem("PROF")
            role_item.setFlags(role_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.custom_staff_table.setItem(row, 0, name_item)
            self.custom_staff_table.setItem(row, 1, role_item)
            self.custom_staff_table.setItem(row, 2, QTableWidgetItem(""))
            self.custom_staff_table.setItem(row, 3, QTableWidgetItem(default_days_text))
            self.custom_staff_table.setItem(row, 4, QTableWidgetItem("ALL"))
            row += 1
        for idx in range(1, int(self.custom_num_tas_spin.value()) + 1):
            name_item = NaturalSortTableItem(f"TA-{idx}")
            role_item = QTableWidgetItem("TA")
            role_item.setFlags(role_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.custom_staff_table.setItem(row, 0, name_item)
            self.custom_staff_table.setItem(row, 1, role_item)
            self.custom_staff_table.setItem(row, 2, QTableWidgetItem(""))
            self.custom_staff_table.setItem(row, 3, QTableWidgetItem(default_days_text))
            self.custom_staff_table.setItem(row, 4, QTableWidgetItem("ALL"))
            row += 1
        self.custom_staff_table.blockSignals(False)
        self.custom_staff_table.setSortingEnabled(was_sorting)

    def _reset_custom_room_table(self) -> None:
        was_sorting = self.custom_room_table.isSortingEnabled()
        self.custom_room_table.setSortingEnabled(False)
        self.custom_room_table.blockSignals(True)
        self.custom_room_table.setRowCount(int(self.custom_room_count_spin.value()))
        defaults = ["LECTURE", "LECTURE", "TUTORIAL", "COMPUTER_LAB", "SPECIALIZED_LAB"]
        for row in range(self.custom_room_table.rowCount()):
            rtype = defaults[row % len(defaults)]
            cat = "MEDIUM"
            cap = ROOM_CATEGORY_CAPACITY[cat]
            self.custom_room_table.setItem(
                row, 0, NaturalSortTableItem(f"{rtype.title()}-{row + 1}")
            )
            self._set_room_enum_cell(row, 1, options=ROOM_TYPE_CHOICES, value=rtype)
            self._set_room_enum_cell(row, 2, options=ROOM_CATEGORY_CHOICES, value=cat)
            self.custom_room_table.setItem(row, 3, self._make_numeric_item(cap))
            self.custom_room_table.setItem(row, 4, QTableWidgetItem("MAIN"))
            self.custom_room_table.setItem(row, 5, QTableWidgetItem(f"BLD-{1 + (row // 6)}"))
            self.custom_room_table.setItem(row, 6, QTableWidgetItem("1"))
            self.custom_room_table.setItem(
                row, 7, QTableWidgetItem("")
            )
            self.custom_room_table.setItem(
                row, 8, QTableWidgetItem("" if rtype != "SPECIALIZED_LAB" else "LAB1")
            )
        self.custom_room_table.blockSignals(False)
        self._apply_room_capacity_mode()
        self.custom_room_table.setSortingEnabled(was_sorting)

    def _on_custom_size_changed(self, *_args: Any) -> None:
        self._reset_custom_program_table()
        self._reset_custom_course_pattern_table()
        self._refresh_staff_course_picker()

    def _reset_custom_program_table(self) -> None:
        rows = int(self.custom_programs_spin.value())
        default_groups = int(self.custom_groups_per_program_spin.value())
        default_group_size = int(self.custom_group_size_spin.value())
        default_courses = int(self.custom_courses_per_program_spin.value())
        was_sorting = self.custom_program_table.isSortingEnabled()
        self.custom_program_table.setSortingEnabled(False)
        self.custom_program_table.blockSignals(True)
        self._custom_program_table_internal_change = True
        self.custom_program_table.setRowCount(rows)
        for row in range(rows):
            self.custom_program_table.setItem(
                row, 0, self._make_locked_item(str(row + 1), numeric=True)
            )
            self.custom_program_table.setItem(
                row, 1, NaturalSortTableItem(f"Program-{row + 1}")
            )
            self.custom_program_table.setItem(
                row, 2, self._make_numeric_item(default_groups)
            )
            self.custom_program_table.setItem(
                row, 3, self._make_numeric_item(default_group_size)
            )
            self.custom_program_table.setItem(
                row, 4, self._make_numeric_item(default_courses)
            )
            self.custom_program_table.setItem(
                row, 5, self._make_numeric_item(default_courses)
            )
        self._custom_program_table_internal_change = False
        self.custom_program_table.blockSignals(False)
        self.custom_program_table.setSortingEnabled(was_sorting)

    def _effective_custom_total_courses(self) -> int:
        if not hasattr(self, "custom_program_table"):
            return int(self.custom_programs_spin.value()) * int(
                self.custom_courses_per_program_spin.value()
            )
        total = 0
        for row in range(self.custom_program_table.rowCount()):
            item = self.custom_program_table.item(row, 4)
            try:
                courses = max(1, int(str(item.text()).strip())) if item is not None else int(
                    self.custom_courses_per_program_spin.value()
                )
            except Exception:
                courses = int(self.custom_courses_per_program_spin.value())
            total += int(courses)
        return max(1, int(total))

    def _find_course_lab_combo_row(self, combo: QComboBox) -> int:
        for row in range(self.custom_course_pattern_table.rowCount()):
            if self.custom_course_pattern_table.cellWidget(row, 5) is combo:
                return row
        return -1

    def _set_course_lab_type_cell(self, row: int, value: str) -> None:
        value_norm = str(value).strip().upper()
        if value_norm not in COURSE_LAB_TYPE_CHOICES:
            value_norm = "NONE"
        self.custom_course_pattern_table.setItem(row, 5, self._make_locked_item(value_norm))
        combo = QComboBox(self.custom_course_pattern_table)
        combo.addItems(list(COURSE_LAB_TYPE_CHOICES))
        combo.blockSignals(True)
        idx = combo.findText(value_norm)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        combo.currentTextChanged.connect(self._on_course_lab_type_changed)
        self.custom_course_pattern_table.setCellWidget(row, 5, combo)

    def _course_pattern_table_text(self, row: int, col: int) -> str:
        widget = self.custom_course_pattern_table.cellWidget(row, col)
        if isinstance(widget, QComboBox):
            return str(widget.currentText()).strip()
        item = self.custom_course_pattern_table.item(row, col)
        return str(item.text()).strip() if item is not None else ""

    def _on_course_lab_type_changed(self, _text: str) -> None:
        if self._custom_course_pattern_table_internal_change:
            return
        sender = self.sender()
        if not isinstance(sender, QComboBox):
            return
        row = self._find_course_lab_combo_row(sender)
        if row < 0:
            return
        self._custom_course_pattern_table_internal_change = True
        try:
            lab_type = self._course_pattern_table_text(row, 5).upper()
            lab_count_item = self.custom_course_pattern_table.item(row, 4)
            try:
                lab_count = max(0, int(str(lab_count_item.text()).strip())) if lab_count_item else 0
            except Exception:
                lab_count = 0
            tag_item = self.custom_course_pattern_table.item(row, 7)
            if tag_item is None:
                tag_item = QTableWidgetItem("")
                self.custom_course_pattern_table.setItem(row, 7, tag_item)
            if lab_count <= 0:
                if lab_type != "NONE":
                    idx = sender.findText("NONE")
                    if idx >= 0:
                        sender.setCurrentIndex(idx)
                tag_item.setText("")
            elif lab_type == "SPECIAL":
                if not str(tag_item.text()).strip():
                    tag_item.setText("LAB1")
            else:
                tag_item.setText("")
        finally:
            self._custom_course_pattern_table_internal_change = False

    def _reset_custom_course_pattern_table(self) -> None:
        existing: Dict[int, Dict[str, Any]] = {}
        if not hasattr(self, "custom_course_pattern_table"):
            return
        for row in range(self.custom_course_pattern_table.rowCount()):
            cid_item = self.custom_course_pattern_table.item(row, 0)
            if cid_item is None:
                continue
            try:
                c_id = int(str(cid_item.text()).strip())
            except Exception:
                continue
            existing[c_id] = {
                "lecture_count": self.custom_course_pattern_table.item(row, 2).text()
                if self.custom_course_pattern_table.item(row, 2) is not None
                else "12",
                "tutorial_count": self.custom_course_pattern_table.item(row, 3).text()
                if self.custom_course_pattern_table.item(row, 3) is not None
                else "12",
                "lab_count": self.custom_course_pattern_table.item(row, 4).text()
                if self.custom_course_pattern_table.item(row, 4) is not None
                else "0",
                "lab_type": self._course_pattern_table_text(row, 5).upper() or "NONE",
                "lab_duration": self.custom_course_pattern_table.item(row, 6).text()
                if self.custom_course_pattern_table.item(row, 6) is not None
                else "2",
                "lab_tag": self.custom_course_pattern_table.item(row, 7).text()
                if self.custom_course_pattern_table.item(row, 7) is not None
                else "",
            }

        total = self._effective_custom_total_courses()
        names = self._parse_csv_names(self.custom_course_names_edit.text())
        was_sorting = self.custom_course_pattern_table.isSortingEnabled()
        self.custom_course_pattern_table.setSortingEnabled(False)
        self.custom_course_pattern_table.blockSignals(True)
        self._custom_course_pattern_table_internal_change = True
        self.custom_course_pattern_table.setRowCount(total)
        for row in range(total):
            c_id = row + 1
            name = names[row % len(names)] if names else f"Course-{c_id}"
            prev = existing.get(c_id, {})
            lec = str(prev.get("lecture_count", "12"))
            tut = str(prev.get("tutorial_count", "12"))
            default_lab_count = "12" if str(prev.get("lab_type", "NONE")).upper() in {"NORMAL", "SPECIAL"} else "0"
            lab_count = str(prev.get("lab_count", default_lab_count))
            lab_type = str(prev.get("lab_type", "NONE")).upper()
            lab_dur = str(prev.get("lab_duration", "2"))
            lab_tag = str(prev.get("lab_tag", ""))
            if lab_type not in COURSE_LAB_TYPE_CHOICES:
                lab_type = "NONE"
            try:
                lab_count_int = max(0, int(str(lab_count).strip()))
            except Exception:
                lab_count_int = 0
            if lab_count_int <= 0:
                lab_type = "NONE"
            self.custom_course_pattern_table.setItem(
                row, 0, self._make_locked_item(str(c_id), numeric=True)
            )
            self.custom_course_pattern_table.setItem(
                row, 1, self._make_locked_item(name, natural=True)
            )
            self.custom_course_pattern_table.setItem(
                row, 2, self._make_numeric_item(lec)
            )
            self.custom_course_pattern_table.setItem(
                row, 3, self._make_numeric_item(tut)
            )
            self.custom_course_pattern_table.setItem(
                row, 4, self._make_numeric_item(lab_count_int)
            )
            self._set_course_lab_type_cell(row, lab_type)
            self.custom_course_pattern_table.setItem(
                row, 6, self._make_numeric_item(lab_dur)
            )
            self.custom_course_pattern_table.setItem(
                row,
                7,
                QTableWidgetItem(lab_tag if lab_type == "SPECIAL" and lab_count_int > 0 else ""),
            )
        self._custom_course_pattern_table_internal_change = False
        self.custom_course_pattern_table.blockSignals(False)
        self.custom_course_pattern_table.setSortingEnabled(was_sorting)

    def _on_custom_program_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._custom_program_table_internal_change:
            return
        if item is None:
            return
        if item.column() not in (2, 3, 4, 5):
            return
        self._custom_program_table_internal_change = True
        try:
            try:
                val = max(1, int(str(item.text()).strip()))
            except Exception:
                if item.column() == 2:
                    val = int(self.custom_groups_per_program_spin.value())
                elif item.column() == 3:
                    val = int(self.custom_group_size_spin.value())
                else:
                    val = int(self.custom_courses_per_program_spin.value())
            item.setText(str(val))
            if item.column() == 4:
                cpg_item = self.custom_program_table.item(item.row(), 5)
                if cpg_item is not None:
                    try:
                        cpg = max(1, int(str(cpg_item.text()).strip()))
                    except Exception:
                        cpg = int(val)
                    cpg_item.setText(str(min(int(val), int(cpg))))
            elif item.column() == 5:
                courses_item = self.custom_program_table.item(item.row(), 4)
                if courses_item is not None:
                    try:
                        courses = max(1, int(str(courses_item.text()).strip()))
                    except Exception:
                        courses = int(self.custom_courses_per_program_spin.value())
                    item.setText(str(min(int(courses), int(val))))
        finally:
            self._custom_program_table_internal_change = False
        self._reset_custom_course_pattern_table()
        self._refresh_staff_course_picker()

    def _on_room_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._room_table_internal_change:
            return
        if item is None:
            return
        row = item.row()
        col = item.column()
        cat_item = self.custom_room_table.item(row, 2)
        cap_item = self.custom_room_table.item(row, 3)
        if cat_item is None or cap_item is None:
            return
        self._room_table_internal_change = True
        try:
            mode = self._room_capacity_mode()
            if col == 1:
                room_type = self._room_table_text(row, 1).upper()
                tags_item = self.custom_room_table.item(row, 8)
                if tags_item is not None:
                    if room_type != "SPECIALIZED_LAB":
                        tags_item.setText("")
                    elif not str(tags_item.text()).strip():
                        tags_item.setText("LAB1")
            if mode == "categorical":
                cat = self._room_table_text(row, 2).upper()
                if cat not in ROOM_CATEGORY_CAPACITY:
                    cat = "MEDIUM"
                    cat_item.setText(cat)
                cap_item.setText(str(ROOM_CATEGORY_CAPACITY[cat]))
            else:
                try:
                    cap = max(1, int(str(cap_item.text()).strip()))
                except Exception:
                    cap = ROOM_CATEGORY_CAPACITY["MEDIUM"]
                cap_item.setText(str(cap))
                inferred_cat = self._infer_room_category(cap)
                cat_item.setText(inferred_cat)
                cat_combo = self.custom_room_table.cellWidget(row, 2)
                if isinstance(cat_combo, QComboBox):
                    idx = cat_combo.findText(inferred_cat)
                    if idx >= 0:
                        cat_combo.setCurrentIndex(idx)
        finally:
            self._room_table_internal_change = False

    def _refresh_staff_course_picker(self, *_args: Any) -> None:
        self.staff_course_picker_combo.clear()
        total = self._effective_custom_total_courses()
        names = self._parse_csv_names(self.custom_course_names_edit.text())
        for c_id in range(1, max(1, total) + 1):
            if names:
                course_name = names[(c_id - 1) % len(names)]
                label = f"{c_id}: {course_name}"
            else:
                label = f"{c_id}: C{c_id:03d}"
            self.staff_course_picker_combo.addItem(label, int(c_id))

    def _on_add_course_to_selected_staff(self) -> None:
        row = self.custom_staff_table.currentRow()
        if row < 0:
            self.set_status("Select a staff row first")
            return
        course_id = self.staff_course_picker_combo.currentData()
        if course_id is None:
            return
        item = self.custom_staff_table.item(int(row), 2)
        if item is None:
            item = QTableWidgetItem("")
            self.custom_staff_table.setItem(int(row), 2, item)
        existing = self._parse_csv_ints(item.text())
        if int(course_id) not in existing:
            existing.append(int(course_id))
            existing = sorted(set(existing))
            item.setText(",".join(str(v) for v in existing))

    def _collect_custom_generation_config(self) -> Dict[str, Any]:
        prof_course_map: Dict[int, List[int]] = {}
        ta_course_map: Dict[int, List[int]] = {}
        prof_days: Dict[int, List[str]] = {}
        ta_days: Dict[int, List[str]] = {}
        prof_weeks: Dict[int, List[int]] = {}
        ta_weeks: Dict[int, List[int]] = {}
        program_overrides: List[Dict[str, Any]] = []
        course_patterns: List[Dict[str, Any]] = []
        prof_idx = 0
        ta_idx = 0
        for row in range(self.custom_staff_table.rowCount()):
            role_item = self.custom_staff_table.item(row, 1)
            courses_item = self.custom_staff_table.item(row, 2)
            days_item = self.custom_staff_table.item(row, 3)
            weeks_item = self.custom_staff_table.item(row, 4)
            role = str(role_item.text()).strip().upper() if role_item else ""
            courses = self._parse_csv_ints(courses_item.text() if courses_item else "")
            days = self._parse_csv_days(days_item.text() if days_item else "")
            weeks = self._parse_csv_weeks(weeks_item.text() if weeks_item else "")
            if role == "PROF":
                prof_idx += 1
                if courses:
                    prof_course_map[prof_idx] = courses
                prof_days[prof_idx] = days
                prof_weeks[prof_idx] = weeks
            elif role == "TA":
                ta_idx += 1
                if courses:
                    ta_course_map[ta_idx] = courses
                ta_days[ta_idx] = days
                ta_weeks[ta_idx] = weeks

        room_specs: List[Dict[str, Any]] = []
        room_capacity_mode = self._room_capacity_mode()
        for row in range(self.custom_room_table.rowCount()):
            name_item = self.custom_room_table.item(row, 0)
            cap_item = self.custom_room_table.item(row, 3)
            campus_item = self.custom_room_table.item(row, 4)
            building_item = self.custom_room_table.item(row, 5)
            floor_item = self.custom_room_table.item(row, 6)
            features_item = self.custom_room_table.item(row, 7)
            tags_item = self.custom_room_table.item(row, 8)
            name = str(name_item.text()).strip() if name_item else f"Room-{row + 1}"
            room_type = self._room_table_text(row, 1).upper() or "LECTURE"
            category = self._room_table_text(row, 2).upper() or "MEDIUM"
            try:
                capacity = max(1, int(str(cap_item.text()).strip())) if cap_item else ROOM_CATEGORY_CAPACITY.get(category, 150)
            except Exception:
                capacity = ROOM_CATEGORY_CAPACITY.get(category, 150)
            campus = str(campus_item.text()).strip().upper() if campus_item else "MAIN"
            building = str(building_item.text()).strip() if building_item else ""
            floor = str(floor_item.text()).strip() if floor_item else ""
            features = [t.strip().upper() for t in str(features_item.text()).split(",") if t.strip()] if features_item else []
            tags = [t.strip().upper() for t in str(tags_item.text()).split(",") if t.strip()] if tags_item else []
            cap_field: int | None = int(capacity)
            if room_capacity_mode == "categorical":
                cap_field = None
            room_specs.append(
                {
                    "name": name,
                    "room_type": room_type,
                    "category": category,
                    "capacity": cap_field,
                    "capacity_mode": room_capacity_mode,
                    "campus": campus or "MAIN",
                    "building": building,
                    "floor": floor,
                    "features": features,
                    "tags": tags,
                }
            )

        for row in range(self.custom_program_table.rowCount()):
            pid_item = self.custom_program_table.item(row, 0)
            name_item = self.custom_program_table.item(row, 1)
            groups_item = self.custom_program_table.item(row, 2)
            group_size_item = self.custom_program_table.item(row, 3)
            courses_item = self.custom_program_table.item(row, 4)
            cpg_item = self.custom_program_table.item(row, 5)
            try:
                pid = int(str(pid_item.text()).strip()) if pid_item is not None else row + 1
                pname = (
                    str(name_item.text()).strip()
                    if name_item is not None and str(name_item.text()).strip()
                    else f"Program-{int(pid)}"
                )
                groups = max(1, int(str(groups_item.text()).strip())) if groups_item is not None else int(self.custom_groups_per_program_spin.value())
                group_size = max(1, int(str(group_size_item.text()).strip())) if group_size_item is not None else int(self.custom_group_size_spin.value())
                courses = max(1, int(str(courses_item.text()).strip())) if courses_item is not None else int(self.custom_courses_per_program_spin.value())
                courses_per_group = max(1, int(str(cpg_item.text()).strip())) if cpg_item is not None else courses
            except Exception:
                continue
            program_overrides.append(
                {
                    "program_id": int(pid),
                    "program_name": str(pname),
                    "groups": int(groups),
                    "group_size": int(group_size),
                    "courses": int(courses),
                    "courses_per_group": min(int(courses), int(courses_per_group)),
                }
            )

        for row in range(self.custom_course_pattern_table.rowCount()):
            cid_item = self.custom_course_pattern_table.item(row, 0)
            lec_item = self.custom_course_pattern_table.item(row, 2)
            tut_item = self.custom_course_pattern_table.item(row, 3)
            lab_count_item = self.custom_course_pattern_table.item(row, 4)
            dur_item = self.custom_course_pattern_table.item(row, 6)
            tag_item = self.custom_course_pattern_table.item(row, 7)
            try:
                c_id = int(str(cid_item.text()).strip()) if cid_item is not None else row + 1
                lecture_count = int(str(lec_item.text()).strip()) if lec_item is not None else 12
                tutorial_count = int(str(tut_item.text()).strip()) if tut_item is not None else 12
                lab_count = int(str(lab_count_item.text()).strip()) if lab_count_item is not None else 0
                lab_duration = int(str(dur_item.text()).strip()) if dur_item is not None else 2
            except Exception:
                continue
            lab_type = self._course_pattern_table_text(row, 5).upper() or "NONE"
            lab_tag = str(tag_item.text()).strip().upper() if tag_item is not None else ""
            if int(lab_count) <= 0:
                lab_type = "NONE"
                lab_tag = ""
            course_patterns.append(
                {
                    "course_id": int(c_id),
                    "lecture_count": int(lecture_count),
                    "tutorial_count": int(tutorial_count),
                    "lab_count": int(max(0, lab_count)),
                    "lab_type": str(lab_type),
                    "lab_duration": int(lab_duration),
                    "lab_tag": str(lab_tag),
                }
            )

        term_blocks = self._parse_term_blocks(self.custom_term_blocks_edit.text())
        calendar_weeks = self._parse_csv_weeks(self.custom_weeks_edit.text())
        if term_blocks:
            calendar_weeks = []
        return {
            "num_programs": int(self.custom_programs_spin.value()),
            "groups_per_program": int(self.custom_groups_per_program_spin.value()),
            "group_size": int(self.custom_group_size_spin.value()),
            "courses_per_program": int(self.custom_courses_per_program_spin.value()),
            "program_overrides": program_overrides,
            "course_patterns": course_patterns,
            "course_names": self._parse_csv_names(self.custom_course_names_edit.text()),
            "num_professors": int(self.custom_num_profs_spin.value()),
            "num_tas": int(self.custom_num_tas_spin.value()),
            "calendar_days": self._parse_csv_days(self.custom_days_edit.text()),
            "calendar_weeks": calendar_weeks,
            "term_blocks": term_blocks,
            "slots_per_day": int(self.custom_slots_per_day_spin.value()),
            "professor_course_map": prof_course_map,
            "ta_course_map": ta_course_map,
            "professor_days": prof_days,
            "ta_days": ta_days,
            "professor_weeks": prof_weeks,
            "ta_weeks": ta_weeks,
            "room_specs": room_specs,
            "room_capacity_mode": room_capacity_mode,
            "seed": 42,
        }

    @staticmethod
    def _local_custom_config_path() -> str:
        return os.path.join(os.path.expanduser("~"), ".planora_custom_config.json")

    @staticmethod
    def _write_custom_config(path: str, config: Dict[str, Any]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, sort_keys=True)

    @staticmethod
    def _read_custom_config(path: str) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Custom config must be a JSON object.")
        return data

    def _apply_custom_generation_config(self, config: Dict[str, Any]) -> None:
        if not isinstance(config, dict):
            raise ValueError("Invalid custom configuration payload.")

        def _ival(key: str, default: int) -> int:
            try:
                return int(config.get(key, default))
            except Exception:
                return int(default)

        num_programs = max(1, _ival("num_programs", int(self.custom_programs_spin.value())))
        groups_per_program = max(
            1, _ival("groups_per_program", int(self.custom_groups_per_program_spin.value()))
        )
        group_size = max(1, _ival("group_size", int(self.custom_group_size_spin.value())))
        courses_per_program = max(
            1, _ival("courses_per_program", int(self.custom_courses_per_program_spin.value()))
        )
        slots_per_day = max(3, _ival("slots_per_day", int(self.custom_slots_per_day_spin.value())))
        num_professors = max(1, _ival("num_professors", int(self.custom_num_profs_spin.value())))
        num_tas = max(1, _ival("num_tas", int(self.custom_num_tas_spin.value())))
        course_names = config.get("course_names", [])
        if not isinstance(course_names, list):
            course_names = []
        course_names_text = ",".join(str(v).strip() for v in course_names if str(v).strip())
        calendar_days = config.get("calendar_days", [])
        if not isinstance(calendar_days, list):
            calendar_days = []
        calendar_days_text = ",".join(
            str(v).strip().upper() for v in calendar_days if str(v).strip()
        )
        calendar_weeks = config.get("calendar_weeks", [])
        if not isinstance(calendar_weeks, list):
            calendar_weeks = []
        term_blocks = config.get("term_blocks", [])
        if not isinstance(term_blocks, list):
            term_blocks = []
        calendar_weeks_text = (
            ",".join(str(int(v)) for v in calendar_weeks) if calendar_weeks else "1-12"
        )
        term_blocks_text = self._format_term_blocks(term_blocks)

        for spin, value in (
            (self.custom_programs_spin, num_programs),
            (self.custom_groups_per_program_spin, groups_per_program),
            (self.custom_group_size_spin, group_size),
            (self.custom_courses_per_program_spin, courses_per_program),
            (self.custom_slots_per_day_spin, slots_per_day),
            (self.custom_num_profs_spin, num_professors),
            (self.custom_num_tas_spin, num_tas),
        ):
            spin.blockSignals(True)
            spin.setValue(int(value))
            spin.blockSignals(False)
        self.custom_days_edit.blockSignals(True)
        self.custom_days_edit.setText(calendar_days_text or "MON,TUE,WED,THU,FRI,SAT")
        self.custom_days_edit.blockSignals(False)
        self.custom_weeks_edit.blockSignals(True)
        self.custom_weeks_edit.setText(calendar_weeks_text)
        self.custom_weeks_edit.blockSignals(False)
        self.custom_term_blocks_edit.blockSignals(True)
        self.custom_term_blocks_edit.setText(term_blocks_text)
        self.custom_term_blocks_edit.blockSignals(False)
        self.custom_course_names_edit.blockSignals(True)
        self.custom_course_names_edit.setText(course_names_text)
        self.custom_course_names_edit.blockSignals(False)

        self._reset_custom_program_table()
        self._reset_custom_course_pattern_table()
        self._reset_custom_staff_table()

        program_overrides = config.get("program_overrides", [])
        if isinstance(program_overrides, list):
            for row_cfg in program_overrides:
                if not isinstance(row_cfg, dict):
                    continue
                try:
                    pid = int(row_cfg.get("program_id"))
                    pname = str(row_cfg.get("program_name", "")).strip() or f"Program-{pid}"
                    groups = max(1, int(row_cfg.get("groups", groups_per_program)))
                    row_group_size = max(1, int(row_cfg.get("group_size", group_size)))
                    courses = max(1, int(row_cfg.get("courses", courses_per_program)))
                    cpg = max(1, int(row_cfg.get("courses_per_group", courses)))
                except Exception:
                    continue
                row = int(pid) - 1
                if not (0 <= row < self.custom_program_table.rowCount()):
                    continue
                self.custom_program_table.setItem(row, 1, NaturalSortTableItem(pname))
                self.custom_program_table.setItem(row, 2, self._make_numeric_item(groups))
                self.custom_program_table.setItem(row, 3, self._make_numeric_item(row_group_size))
                self.custom_program_table.setItem(row, 4, self._make_numeric_item(courses))
                self.custom_program_table.setItem(
                    row, 5, self._make_numeric_item(min(courses, cpg))
                )

        self._reset_custom_course_pattern_table()
        course_patterns = config.get("course_patterns", [])
        if isinstance(course_patterns, list):
            by_course: Dict[int, Dict[str, Any]] = {}
            for row_cfg in course_patterns:
                if not isinstance(row_cfg, dict):
                    continue
                try:
                    c_id = int(row_cfg.get("course_id"))
                except Exception:
                    continue
                by_course[int(c_id)] = row_cfg
            for row in range(self.custom_course_pattern_table.rowCount()):
                cid_item = self.custom_course_pattern_table.item(row, 0)
                if cid_item is None:
                    continue
                try:
                    c_id = int(str(cid_item.text()).strip())
                except Exception:
                    continue
                row_cfg = by_course.get(int(c_id))
                if not row_cfg:
                    continue
                try:
                    lec = max(0, int(row_cfg.get("lecture_count", 12)))
                    tut = max(0, int(row_cfg.get("tutorial_count", 12)))
                    lab_count = max(
                        0,
                        int(
                            row_cfg.get(
                                "lab_count",
                                12 if str(row_cfg.get("lab_type", "NONE")).strip().upper() in {"NORMAL", "SPECIAL"} else 0,
                            )
                        ),
                    )
                    lab_type = str(row_cfg.get("lab_type", "NONE")).strip().upper()
                    lab_dur = max(1, int(row_cfg.get("lab_duration", 2)))
                    lab_tag = str(row_cfg.get("lab_tag", "")).strip().upper()
                except Exception:
                    continue
                self.custom_course_pattern_table.setItem(row, 2, self._make_numeric_item(lec))
                self.custom_course_pattern_table.setItem(row, 3, self._make_numeric_item(tut))
                self.custom_course_pattern_table.setItem(
                    row, 4, self._make_numeric_item(lab_count)
                )
                if lab_count <= 0:
                    lab_type = "NONE"
                lab_combo = self.custom_course_pattern_table.cellWidget(row, 5)
                if isinstance(lab_combo, QComboBox):
                    idx = lab_combo.findText(lab_type)
                    if idx >= 0:
                        lab_combo.setCurrentIndex(idx)
                self.custom_course_pattern_table.setItem(
                    row, 6, self._make_numeric_item(lab_dur)
                )
                self.custom_course_pattern_table.setItem(
                    row, 7, QTableWidgetItem(lab_tag if lab_type == "SPECIAL" and lab_count > 0 else "")
                )

        professor_course_map = config.get("professor_course_map", {}) or {}
        ta_course_map = config.get("ta_course_map", {}) or {}
        professor_days = config.get("professor_days", {}) or {}
        ta_days = config.get("ta_days", {}) or {}
        professor_weeks = config.get("professor_weeks", {}) or {}
        ta_weeks = config.get("ta_weeks", {}) or {}
        for idx in range(1, int(num_professors) + 1):
            row = idx - 1
            if row >= self.custom_staff_table.rowCount():
                break
            courses = professor_course_map.get(idx, professor_course_map.get(str(idx), [])) or []
            days = professor_days.get(idx, professor_days.get(str(idx), [])) or []
            weeks = professor_weeks.get(idx, professor_weeks.get(str(idx), [])) or []
            self.custom_staff_table.setItem(
                row, 2, QTableWidgetItem(",".join(str(int(c)) for c in courses if str(c).strip()))
            )
            day_text = ",".join(str(d).strip().upper() for d in days if str(d).strip())
            self.custom_staff_table.setItem(row, 3, QTableWidgetItem(day_text))
            if weeks:
                week_text = ",".join(str(int(w)) for w in weeks if str(w).strip())
            else:
                week_text = "ALL"
            self.custom_staff_table.setItem(row, 4, QTableWidgetItem(week_text))
        for idx in range(1, int(num_tas) + 1):
            row = int(num_professors) + idx - 1
            if row >= self.custom_staff_table.rowCount():
                break
            courses = ta_course_map.get(idx, ta_course_map.get(str(idx), [])) or []
            days = ta_days.get(idx, ta_days.get(str(idx), [])) or []
            weeks = ta_weeks.get(idx, ta_weeks.get(str(idx), [])) or []
            self.custom_staff_table.setItem(
                row, 2, QTableWidgetItem(",".join(str(int(c)) for c in courses if str(c).strip()))
            )
            day_text = ",".join(str(d).strip().upper() for d in days if str(d).strip())
            self.custom_staff_table.setItem(row, 3, QTableWidgetItem(day_text))
            if weeks:
                week_text = ",".join(str(int(w)) for w in weeks if str(w).strip())
            else:
                week_text = "ALL"
            self.custom_staff_table.setItem(row, 4, QTableWidgetItem(week_text))

        room_specs = config.get("room_specs", [])
        if isinstance(room_specs, list) and room_specs:
            self.custom_room_count_spin.blockSignals(True)
            self.custom_room_count_spin.setValue(max(1, len(room_specs)))
            self.custom_room_count_spin.blockSignals(False)
            mode_raw = config.get("room_capacity_mode")
            if mode_raw is None and room_specs:
                mode_raw = room_specs[0].get("capacity_mode")
            mode = str(mode_raw or "numeric").strip().lower()
            mode = "categorical" if mode.startswith("cat") else "numeric"
            mode_idx = self.custom_room_capacity_mode_combo.findData(mode)
            if mode_idx >= 0:
                self.custom_room_capacity_mode_combo.setCurrentIndex(mode_idx)
            self._reset_custom_room_table()
            for row, room_cfg in enumerate(room_specs):
                if row >= self.custom_room_table.rowCount() or not isinstance(room_cfg, dict):
                    break
                name = str(room_cfg.get("name", "")).strip() or f"Room-{row + 1}"
                rtype = str(room_cfg.get("room_type", "LECTURE")).strip().upper()
                cat = str(room_cfg.get("category", "MEDIUM")).strip().upper()
                cap = room_cfg.get("capacity", ROOM_CATEGORY_CAPACITY.get(cat, 150))
                try:
                    cap_int = max(1, int(cap))
                except Exception:
                    cap_int = int(ROOM_CATEGORY_CAPACITY.get(cat, 150))
                campus = str(room_cfg.get("campus", "MAIN")).strip().upper() or "MAIN"
                building = str(room_cfg.get("building", "")).strip()
                floor = str(room_cfg.get("floor", "")).strip()
                features_raw = room_cfg.get("features", []) or []
                features = ",".join(
                    str(t).strip().upper() for t in features_raw if str(t).strip()
                )
                tags_raw = room_cfg.get("tags", []) or []
                tags = ",".join(str(t).strip().upper() for t in tags_raw if str(t).strip())

                self.custom_room_table.setItem(row, 0, NaturalSortTableItem(name))
                type_combo = self.custom_room_table.cellWidget(row, 1)
                if isinstance(type_combo, QComboBox):
                    idx = type_combo.findText(rtype)
                    if idx >= 0:
                        type_combo.setCurrentIndex(idx)
                cat_combo = self.custom_room_table.cellWidget(row, 2)
                if isinstance(cat_combo, QComboBox):
                    idx = cat_combo.findText(cat)
                    if idx >= 0:
                        cat_combo.setCurrentIndex(idx)
                self.custom_room_table.setItem(row, 3, self._make_numeric_item(cap_int))
                self.custom_room_table.setItem(row, 4, QTableWidgetItem(campus))
                self.custom_room_table.setItem(row, 5, QTableWidgetItem(building))
                self.custom_room_table.setItem(row, 6, QTableWidgetItem(floor))
                self.custom_room_table.setItem(row, 7, QTableWidgetItem(features))
                self.custom_room_table.setItem(row, 8, QTableWidgetItem(tags))

        self._apply_room_capacity_mode()
        self._refresh_staff_course_picker()
        self._normalize_custom_table_item_types()

    def on_save_custom_config_local(self) -> None:
        try:
            config = self._collect_custom_generation_config()
            path = self._local_custom_config_path()
            self._write_custom_config(path, config)
            self.set_status(f"Saved local custom config to {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Custom config error", str(exc))

    def on_save_custom_config_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save custom generation config",
            "custom_generator_config.json",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            config = self._collect_custom_generation_config()
            self._write_custom_config(path, config)
            self.set_status(f"Saved custom config to {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Custom config error", str(exc))

    def on_load_custom_config_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load custom generation config",
            "",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            config = self._read_custom_config(path)
            self._apply_custom_generation_config(config)
            self.set_status(f"Loaded custom config from {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Custom config error", str(exc))

    def _load_custom_config_local(self, *, silent: bool = False) -> None:
        path = self._local_custom_config_path()
        if not os.path.exists(path):
            return
        try:
            config = self._read_custom_config(path)
            self._apply_custom_generation_config(config)
            if not silent:
                self.set_status(f"Loaded local custom config from {path}")
        except Exception:
            if not silent:
                traceback.print_exc()
            if not silent:
                QMessageBox.warning(
                    self,
                    "Custom config warning",
                    f"Failed to load local custom configuration from {path}.",
                )

    def on_generate(self):
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Wait for solving to finish first.")
            return

        mode = self.mode_combo.currentText()
        try:
            self.product_scenario = self._build_product_scenario_from_controls(str(mode))
            inst = compile_scenario_instance(self.product_scenario)
            self._apply_constraint_settings(inst)
            check_staff_weekly_capacity(inst)  # logs warnings to stdout
            self.inst = inst
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Generate error", str(e))
            return

        self.base_schedule = {}
        self._set_manual_highlight_base({})
        self.current_schedule = {}
        self._last_solver_result_meta = {}
        self.locked_activities = {}
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        self.set_status(f"Instance generated ({mode})")
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self._load_constraint_controls_from_instance(self.inst)
        self._append_audit_log(
            "generate_instance",
            {"mode": str(mode), "activities": int(len(self.inst.activities))},
        )
        self._save_persistent_history()
