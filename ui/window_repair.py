from __future__ import annotations

from ui.window_runtime import *  # noqa: F401,F403
from ui.window_runtime import _window_global


class WindowRepairMixin:

    def _render_empty_calendar(
        self,
        days: List[str] | Tuple[str, ...] | None,
        slots_per_day: int | None,
        *,
        week_label: str = "Week -",
    ) -> None:
        render_days = list(days) if days else list(self.DEFAULT_PREVIEW_DAYS)
        render_slots = int(slots_per_day) if slots_per_day and int(slots_per_day) > 0 else int(self.DEFAULT_PREVIEW_SLOTS)
        self.table.clear()
        self.table.setRowCount(len(render_days))
        self.table.setColumnCount(render_slots)
        self.table.setVerticalHeaderLabels(render_days)
        self.table.setHorizontalHeaderLabels([f"S{idx + 1}" for idx in range(render_slots)])
        self._cell_activity_map = {}
        for row, day in enumerate(render_days):
            for col in range(render_slots):
                item = QTableWidgetItem("")
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
                )
                item.setForeground(QBrush(QColor("#f5f5f5")))
                item.setToolTip(f"{week_label} | {day} S{col + 1}\nActivities: none")
                self.table.setItem(row, col, item)
                self._cell_activity_map[(row, col)] = []
        self._schedule_table_relayout()

    def _selected_cell_day_slot(self) -> Tuple[str, int] | None:
        if self.inst is None:
            return None
        if self.selected_cell_row is None or self.selected_cell_col is None:
            return None
        if not (0 <= int(self.selected_cell_row) < len(self.inst.days)):
            return None
        if not (0 <= int(self.selected_cell_col) < int(self.inst.slots_per_day)):
            return None
        return (self.inst.days[int(self.selected_cell_row)], int(self.selected_cell_col))

    def _show_held_targets_dialog(self) -> None:
        if self.inst is None or self.held_activity_id is None:
            self.set_status("No held activity")
            return
        week = self._current_week()
        if week is None:
            self.set_status("Select a week first")
            return
        analysis_map = self._held_move_analysis_from_cache(
            int(week), compute_scores=True, include_conflicts=False
        )
        if not analysis_map:
            self._request_held_move_analysis_async(
                int(week), compute_scores=True, include_conflicts=False
            )
            self.set_status("Computing held target analysis in background...")
            return
        valid_targets: List[str] = []
        for d in self.inst.days:
            for s in range(self.inst.slots_per_day):
                info = analysis_map.get((str(d), int(s)))
                if not info or not bool(info.get("ok", False)):
                    continue
                score_after = info.get("score_after")
                score_delta = info.get("score_delta")
                if isinstance(score_after, int) and isinstance(score_delta, int):
                    valid_targets.append(
                        f"{d} S{s + 1} | soft penalty {int(score_after)} "
                        f"(Δ {int(score_delta):+d}, {self._describe_penalty_delta(int(score_delta))})"
                    )
                else:
                    valid_targets.append(f"{d} S{s + 1}")
        if not valid_targets:
            QMessageBox.information(
                self,
                "Held activity targets",
                f"No valid target slots in week {int(week)} for the held activity under current hard constraints.",
            )
        else:
            QMessageBox.information(
                self,
                "Held activity targets",
                f"Valid slots in week {int(week)}:\n" + "\n".join(valid_targets),
            )

    def _refresh_quick_actions(self) -> None:
        has_inst = self.inst is not None
        week = self._current_week()
        selected_cell = self._selected_cell_day_slot()
        if has_inst and selected_cell and week is not None:
            day, slot = selected_cell
            selected_text = f"Selected: {day} S{int(slot) + 1} (Week {week})"
            self.selected_slot_label.setText(selected_text)
            self.selected_slot_label.setToolTip(selected_text)
        else:
            self.selected_slot_label.setText("Selected: none")
            self.selected_slot_label.setToolTip("Selected: none")

        selected_ids: List[int] = []
        if selected_cell and has_inst and week is not None:
            row = int(self.selected_cell_row) if self.selected_cell_row is not None else -1
            col = int(self.selected_cell_col) if self.selected_cell_col is not None else -1
            selected_ids = list(self._cell_activity_map.get((row, col), []))

        self.selected_activity_combo.blockSignals(True)
        self.selected_activity_combo.clear()
        for a_id in selected_ids:
            self.selected_activity_combo.addItem(self._activity_title(int(a_id)), int(a_id))
        if selected_ids:
            target_id = (
                int(self.selected_activity_id)
                if self.selected_activity_id is not None and int(self.selected_activity_id) in selected_ids
                else int(selected_ids[0])
            )
            idx = self.selected_activity_combo.findData(target_id)
            if idx >= 0:
                self.selected_activity_combo.setCurrentIndex(idx)
            self.selected_activity_id = target_id
        else:
            self.selected_activity_id = None
        self.selected_activity_combo.blockSignals(False)

        if self.held_activity_id is not None and self.held_activity_id in self.current_schedule:
            held_id = int(self.held_activity_id)
            held_info = self.current_schedule.get(held_id, {})
            held_day = str(held_info.get("day", "?"))
            held_slot = int(held_info.get("slot", 0)) + 1
            compact = f"Held: A{held_id} ({held_day} S{held_slot})"
            self.held_slot_label.setText(compact)
            self.held_slot_label.setToolTip(self._activity_title(held_id))
        else:
            self.held_slot_label.setText("Held: none")
            self.held_slot_label.setToolTip("Held: none")

        has_selected_activity = self.selected_activity_id is not None
        bulk_selected_ids = self._selected_activity_ids_from_table_selection()
        has_bulk_selection = bool(bulk_selected_ids)
        has_held = (
            self.held_activity_id is not None
            and self.held_activity_id in self.current_schedule
        )
        has_selected_slot = selected_cell is not None

        self.selected_activity_combo.setEnabled(bool(selected_ids))
        self.quick_edit_btn.setEnabled(has_selected_activity)
        self.quick_hold_btn.setEnabled(has_selected_activity)
        self.quick_bulk_btn.setEnabled(has_bulk_selection)
        self.quick_time_lock_btn.setEnabled(has_selected_activity)
        self.quick_room_lock_btn.setEnabled(has_selected_activity)
        self.quick_move_btn.setEnabled(has_held and has_selected_slot)
        self.quick_explain_btn.setEnabled(has_held and has_selected_slot)
        self.quick_swap_btn.setEnabled(
            has_held and has_selected_activity and int(self.held_activity_id) != int(self.selected_activity_id)
        )
        self.quick_targets_btn.setEnabled(has_held)
        self.quick_release_btn.setEnabled(has_held)
        if not self._live_improve_mode:
            self._defer_layout_stabilization()

    def on_table_cell_clicked(self, row: int, col: int) -> None:
        try:
            self.selected_cell_row = int(row)
            self.selected_cell_col = int(col)
            self._refresh_quick_actions()
        except Exception:
            traceback.print_exc()
            self.set_status("Failed to select cell")

    def _on_schedule_drag_requested(self, row: int, col: int) -> None:
        if self.inst is None or not self.current_schedule:
            return
        week = self._current_week()
        if week is None or not (0 <= int(row) < len(self.inst.days)):
            return
        day = str(self.inst.days[int(row)])
        act_ids = list(self._cell_activity_ids_for_view(day, int(col), int(week)))
        if not act_ids:
            return
        a_id = None
        if self.selected_activity_id is not None and int(self.selected_activity_id) in act_ids:
            a_id = int(self.selected_activity_id)
        elif len(act_ids) == 1:
            a_id = int(act_ids[0])
        else:
            a_id = self._choose_activity_from_ids(act_ids, "Drag activity")
        if a_id is not None:
            self._set_held_activity(int(a_id))
            self.set_status(
                f"Dragging {self._activity_title(int(a_id))}. Drop it on a target slot to move safely."
            )

    def _on_schedule_drop_requested(self, row: int, col: int) -> None:
        if self.inst is None or self.held_activity_id is None:
            return
        week = self._current_week()
        if week is None or not (0 <= int(row) < len(self.inst.days)):
            return
        day = str(self.inst.days[int(row)])
        self._attempt_move_held_to(str(day), int(col), int(week))

    def on_selected_activity_changed(self, _idx: int = -1) -> None:
        data = self.selected_activity_combo.currentData()
        self.selected_activity_id = int(data) if data is not None else None
        self._refresh_quick_actions()

    def on_quick_edit_selected(self) -> None:
        if self.selected_activity_id is None:
            return
        if self.selected_cell_row is None or self.selected_cell_col is None:
            return
        self.on_cell_double_clicked(int(self.selected_cell_row), int(self.selected_cell_col))
        self._refresh_quick_actions()

    def on_quick_hold_selected(self) -> None:
        if self.selected_activity_id is None:
            return
        self._set_held_activity(int(self.selected_activity_id))
        self._refresh_quick_actions()

    def on_quick_bulk_edit_selected(self) -> None:
        if self.inst is None or not self.current_schedule:
            return
        selected_ids = self._selected_activity_ids_from_table_selection()
        if not selected_ids:
            self.set_status("Select timetable cells first")
            return
        dialog_cls = _window_global("BulkEditDialog", BulkEditDialog)
        dlg = dialog_cls(self, weeks=list(self.inst.weeks), count=len(selected_ids))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        changes = dlg.get_values()
        updated = self._clone_schedule()
        updated_locks = {
            int(a_id): dict(lock)
            for a_id, lock in self.locked_activities.items()
            if isinstance(lock, dict)
        }
        skipped: List[int] = []
        changed_count = 0
        for a_id in selected_ids:
            info = updated.get(int(a_id))
            if info is None:
                continue
            new_week = int(info["week"])
            week_mode = str(changes.get("week_mode", "keep"))
            if week_mode == "set":
                new_week = int(changes.get("target_week"))
            elif week_mode == "shift":
                new_week = int(info["week"]) + int(changes.get("week_delta", 0))
            if new_week not in set(int(w) for w in self.inst.weeks):
                skipped.append(int(a_id))
                continue
            ok, _reason = self.check_move(
                int(a_id),
                str(info["day"]),
                int(info["slot"]),
                int(info["room_id"]),
                int(info["staff_id"]),
                int(new_week),
                schedule_override=updated,
            )
            if week_mode != "keep" and not ok:
                skipped.append(int(a_id))
                continue
            if week_mode != "keep":
                info["week"] = int(new_week)
                changed_count += 1

            note_mode = str(changes.get("note_mode", "keep"))
            if note_mode == "set":
                info["admin_note"] = str(changes.get("note_text", "")).strip()
                changed_count += 1
            elif note_mode == "clear":
                if "admin_note" in info:
                    info.pop("admin_note", None)
                    changed_count += 1

            fixed = dict(updated_locks.get(int(a_id), {}))
            time_mode = str(changes.get("time_lock_mode", "keep"))
            if time_mode == "enable":
                fixed["day"] = str(info["day"])
                fixed["slot"] = int(info["slot"])
                changed_count += 1
            elif time_mode == "disable":
                if "day" in fixed or "slot" in fixed:
                    fixed.pop("day", None)
                    fixed.pop("slot", None)
                    changed_count += 1

            room_mode = str(changes.get("room_lock_mode", "keep"))
            if room_mode == "enable":
                fixed["room_id"] = int(info["room_id"])
                changed_count += 1
            elif room_mode == "disable":
                if "room_id" in fixed:
                    fixed.pop("room_id", None)
                    changed_count += 1

            if fixed:
                updated_locks[int(a_id)] = fixed
            else:
                updated_locks.pop(int(a_id), None)

        if changed_count <= 0:
            self.set_status("Bulk edit made no changes")
            return
        self._push_undo_state()
        self.locked_activities = updated_locks
        self._commit_schedule(
            updated,
            f"Bulk edit applied to {int(len(selected_ids) - len(skipped))} activities"
            + (f"; skipped {len(skipped)}" if skipped else ""),
        )
        self._refresh_quick_actions()

    def on_quick_move_held_here(self) -> None:
        cell = self._selected_cell_day_slot()
        if cell is None:
            return
        week = self._current_week()
        if week is None:
            return
        day, slot = cell
        self._attempt_move_held_to(str(day), int(slot), int(week))
        self._refresh_quick_actions()

    def on_quick_explain_move(self) -> None:
        if self.inst is None or self.held_activity_id is None:
            return
        cell = self._selected_cell_day_slot()
        week = self._current_week()
        if cell is None or week is None:
            return
        held_id = int(self.held_activity_id)
        info = self.current_schedule.get(held_id)
        if info is None:
            return
        target_day, target_slot = cell
        result = explain_candidate_slot(
            self.inst,
            self.current_schedule,
            activity_id=int(held_id),
            week=int(week),
            day=str(target_day),
            slot=int(target_slot),
            room_id=int(info["room_id"]),
            staff_id=int(info["staff_id"]),
        )
        ok = bool(result.get("valid", False))
        reason = (
            "Candidate placement is valid."
            if ok
            else "; ".join(str(line) for line in (result.get("reasons") or [])[:3])
        )
        conflicts = []
        if not ok:
            conflicts = self._find_move_conflicts(
                held_id,
                str(target_day),
                int(target_slot),
                int(info["room_id"]),
                int(info["staff_id"]),
                int(week),
            )
        text = build_move_explanation_text(
            activity_id=int(held_id),
            target_week=int(week),
            target_day=str(target_day),
            target_slot=int(target_slot),
            valid=bool(ok),
            reason=str(reason),
            conflicts=conflicts,
        )
        delta = int(result.get("soft_penalty_delta", 0))
        text += f"\n\nSoft penalty delta: {delta:+d}"
        QMessageBox.information(self, "Move Explanation", text)

    def on_explain_candidate_slot(self) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule loaded")
            return
        activity_id = self.why_not_activity_combo.currentData()
        week = self.why_not_week_combo.currentData()
        day = self.why_not_day_combo.currentData()
        slot = self.why_not_slot_combo.currentData()
        if activity_id is None or week is None or day is None or slot is None:
            self.why_not_output_text.setPlainText("Select an activity, week, day, and slot.")
            return
        info = self.current_schedule.get(int(activity_id))
        room_id = int(info["room_id"]) if info and info.get("room_id") is not None else None
        staff_id = int(info["staff_id"]) if info and info.get("staff_id") is not None else None
        try:
            result = explain_candidate_slot(
                self.inst,
                self.current_schedule,
                activity_id=int(activity_id),
                week=int(week),
                day=str(day),
                slot=int(slot),
                room_id=room_id,
                staff_id=staff_id,
            )
        except Exception as exc:
            traceback.print_exc()
            self.why_not_output_text.setPlainText(str(exc))
            return
        lines = [
            f"Activity A{int(activity_id)} -> W{int(week)} {str(day)} S{int(slot) + 1}",
            f"Valid: {bool(result.get('valid', False))}",
            f"Soft penalty delta: {int(result.get('soft_penalty_delta', 0)):+d}",
        ]
        reasons = list(result.get("reasons", []) or [])
        if reasons:
            lines.append("Reasons:")
            lines.extend(f"- {line}" for line in reasons[:8])
        self.why_not_output_text.setPlainText("\n".join(lines))
        self.set_status("Candidate slot explanation updated")

    def on_quick_swap_held_with_selected(self) -> None:
        if self.held_activity_id is None or self.selected_activity_id is None:
            return
        if int(self.held_activity_id) == int(self.selected_activity_id):
            self.set_status("Held and selected activity are the same")
            return
        ok, reason = self._attempt_swap_timeslots(
            int(self.held_activity_id), int(self.selected_activity_id)
        )
        if not ok:
            QMessageBox.warning(self, "Swap blocked", reason)
        self._refresh_quick_actions()

    def on_quick_toggle_time_lock(self) -> None:
        if self.selected_activity_id is None:
            return
        self._toggle_activity_lock(int(self.selected_activity_id), time_lock=True)
        self._refresh_quick_actions()

    def on_quick_toggle_room_lock(self) -> None:
        if self.selected_activity_id is None:
            return
        self._toggle_activity_lock(int(self.selected_activity_id), time_lock=False)
        self._refresh_quick_actions()

    def on_quick_show_held_targets(self) -> None:
        self._show_held_targets_dialog()
        self._refresh_quick_actions()

    def on_quick_release_held(self) -> None:
        self._clear_held_activity()
        self._refresh_quick_actions()

    def _sync_locks_to_instance(self) -> None:
        if self.inst is None:
            return
        self.inst.locked_activities = {
            int(a_id): dict(lock) for a_id, lock in self.locked_activities.items()
        }

    def _validate_schedule_hard_errors(
        self,
        schedule: Dict[int, Dict[str, Any]],
        *,
        require_all: bool = True,
    ) -> List[str]:
        if self.inst is None or not schedule:
            return []
        original_weeks: Dict[int, int] = {}
        for a_id, act in self.inst.activities.items():
            original_weeks[int(a_id)] = int(act.week)
        try:
            self._sync_instance_activity_weeks_from_schedule(schedule)
            return validate_schedule_against_instance(
                self.inst,
                schedule,
                strict_rooms=True,
                require_all_activities=bool(require_all),
            )
        except Exception:
            return []
        finally:
            for a_id, week in original_weeks.items():
                act = self.inst.activities.get(int(a_id))
                if act is not None:
                    act.week = int(week)

    def _collect_conflict_errors(self) -> List[str]:
        return self._validate_schedule_hard_errors(
            self.current_schedule, require_all=True
        )

    def _activity_conflict_context(self, a_id: int) -> str:
        inst = self.inst
        info = self.current_schedule.get(int(a_id))
        if inst is None or info is None:
            return f"A{int(a_id)}"

        room_id = info.get("room_id")
        room_name = "Unassigned"
        if room_id is not None:
            room = inst.rooms.get(int(room_id))
            if room is not None:
                room_name = f"{room.name} [id {int(room_id)}]"
            else:
                room_name = f"R{int(room_id)}"

        staff_id = info.get("staff_id")
        staff_name = "Unknown"
        if staff_id is not None:
            staff = inst.staff.get(int(staff_id))
            if staff is not None:
                staff_name = f"{staff.name} [id {int(staff_id)}]"
            else:
                staff_name = f"S{int(staff_id)}"

        group_parts: List[str] = []
        for g_id in info.get("group_ids", []) or []:
            try:
                gid = int(g_id)
            except Exception:
                continue
            grp = inst.groups.get(gid)
            if grp is not None:
                group_parts.append(f"{grp.name} [id {gid}]")
            else:
                group_parts.append(f"G{gid}")
        group_text = ", ".join(group_parts) if group_parts else "-"

        day = str(info.get("day", "?"))
        slot = int(info.get("slot", 0)) + 1
        week = int(info.get("week", 0))
        return (
            f"A{int(a_id)} @ W{week} {day} S{slot} | "
            f"room={room_name} | staff={staff_name} | groups={group_text}"
        )

    def _humanize_conflict_error(self, message: str) -> str:
        msg = str(message or "")

        def _slot_repl(match: re.Match[str]) -> str:
            try:
                raw_slot = int(match.group(1))
            except Exception:
                return match.group(0)
            return f"slot S{raw_slot + 1}"

        text = re.sub(r"\bslot\s+(-?\d+)\b", _slot_repl, msg)
        activity_ids: List[int] = []
        for token in re.findall(r"\bA(\d+)\b", text):
            try:
                a_id = int(token)
            except Exception:
                continue
            if a_id not in activity_ids:
                activity_ids.append(a_id)

        if not activity_ids:
            return text

        details: List[str] = []
        for a_id in activity_ids[:2]:
            details.append(self._activity_conflict_context(a_id))

        if len(activity_ids) >= 2:
            a0 = self.current_schedule.get(int(activity_ids[0]), {})
            a1 = self.current_schedule.get(int(activity_ids[1]), {})
            lower = text.lower()
            if "group overlap" in lower:
                shared = sorted(
                    set(int(g) for g in (a0.get("group_ids") or []))
                    & set(int(g) for g in (a1.get("group_ids") or []))
                )
                if shared:
                    grp_labels: List[str] = []
                    if self.inst is not None:
                        for gid in shared:
                            grp = self.inst.groups.get(int(gid))
                            grp_labels.append(
                                f"{grp.name} [id {int(gid)}]"
                                if grp is not None
                                else f"G{int(gid)}"
                            )
                    else:
                        grp_labels = [f"G{int(gid)}" for gid in shared]
                    details.append("shared groups=" + ", ".join(grp_labels))
            if "room overlap" in lower:
                rid0 = a0.get("room_id")
                rid1 = a1.get("room_id")
                if rid0 is not None and rid1 is not None and int(rid0) == int(rid1):
                    room_desc = f"R{int(rid0)}"
                    if self.inst is not None:
                        room = self.inst.rooms.get(int(rid0))
                        if room is not None:
                            room_desc = f"{room.name} [id {int(rid0)}]"
                    details.append(f"same room={room_desc}")
            if "staff overlap" in lower:
                sid0 = a0.get("staff_id")
                sid1 = a1.get("staff_id")
                if sid0 is not None and sid1 is not None and int(sid0) == int(sid1):
                    staff_desc = f"S{int(sid0)}"
                    if self.inst is not None:
                        staff = self.inst.staff.get(int(sid0))
                        if staff is not None:
                            staff_desc = f"{staff.name} [id {int(sid0)}]"
                    details.append(f"same staff={staff_desc}")

        return f"{text} | " + " | ".join(details)

    def _jump_to_activity(self, a_id: int) -> bool:
        if self.inst is None:
            return False
        info = self.current_schedule.get(int(a_id))
        if info is None:
            return False

        week = int(info.get("week", 0))
        day = str(info.get("day", ""))
        slot = int(info.get("slot", 0))

        week_idx = self.week_combo.findData(int(week))
        if week_idx >= 0 and week_idx != self.week_combo.currentIndex():
            self.week_combo.setCurrentIndex(week_idx)

        all_idx = self.view_type_combo.findText("All")
        if all_idx >= 0 and all_idx != self.view_type_combo.currentIndex():
            self.view_type_combo.setCurrentIndex(all_idx)
        else:
            self.update_table()

        if day not in self.inst.days:
            return False
        row = int(self.inst.days.index(day))
        col = int(max(0, min(slot, int(self.inst.slots_per_day) - 1)))
        self.selected_cell_row = row
        self.selected_cell_col = col
        self.selected_activity_id = int(a_id)
        self._refresh_quick_actions()

        try:
            self.table.setCurrentCell(row, col)
            item = self.table.item(row, col)
            if item is not None:
                self.table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
        except Exception:
            pass
        return True

    def _solve_current_conflicts(self, errors: List[str] | None = None) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule to repair")
            return
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Solver already running.")
            return

        raw_errors = list(errors or self._collect_conflict_errors())
        if not raw_errors:
            self.set_status("No hard conflicts to solve")
            return

        conflict_ids: Set[int] = set()
        for err in raw_errors:
            for token in re.findall(r"\bA(\d+)\b", str(err)):
                try:
                    conflict_ids.add(int(token))
                except Exception:
                    continue

        if not conflict_ids:
            self.set_status("Could not map conflicts to activities; running full solve")
            self.on_solve()
            return

        prior_locks = {
            int(a_id): dict(lock)
            for a_id, lock in self.locked_activities.items()
            if isinstance(lock, dict)
        }
        build_locks = _window_global("build_freeze_locks", build_freeze_locks)
        freeze_locks = build_locks(
            self.current_schedule,
            unlocked_activity_ids=set(int(a_id) for a_id in conflict_ids),
        )
        self.locked_activities = freeze_locks
        self._sync_locks_to_instance()
        self._restore_locks_after_solve = prior_locks
        self._append_audit_log(
            "conflict_repair_started",
            {
                "conflicts": int(len(raw_errors)),
                "conflict_activities": int(len(conflict_ids)),
                "frozen_activities": int(len(freeze_locks)),
            },
        )
        self.set_status(
            f"Repairing conflicts: {len(raw_errors)} issue(s), "
            f"{len(conflict_ids)} conflicting activity(ies)"
        )
        self._start_solver_process(keep_locks=True)

    def on_fix_current_conflicts(self) -> None:
        self._solve_current_conflicts()

    def _toggle_activity_lock(self, a_id: int, *, time_lock: bool) -> None:
        if a_id not in self.current_schedule:
            return
        self._push_undo_state()
        info = self.current_schedule[a_id]
        fixed = dict(self.locked_activities.get(a_id, {}))
        if time_lock:
            if "day" in fixed and "slot" in fixed:
                fixed.pop("day", None)
                fixed.pop("slot", None)
            else:
                fixed["day"] = str(info["day"])
                fixed["slot"] = int(info["slot"])
        else:
            if "room_id" in fixed:
                fixed.pop("room_id", None)
            else:
                fixed["room_id"] = int(info["room_id"])
        if fixed:
            self.locked_activities[a_id] = fixed
        else:
            self.locked_activities.pop(a_id, None)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        lock_name = "time" if time_lock else "room"
        self.set_status(f"Toggled {lock_name} lock for A{a_id}")
        self._refresh_history_buttons()

    def _activity_title(
        self,
        a_id: int,
        schedule: Dict[int, Dict[str, Any]] | None = None,
    ) -> str:
        inst = self.inst
        if inst is None:
            return f"A{a_id}"
        info = None
        if schedule is not None:
            info = schedule.get(a_id)
        elif self.current_schedule:
            info = self.current_schedule.get(a_id)
        course_code = ""
        if info is not None:
            course = inst.courses.get(int(info["course_id"]))
            if course is not None:
                course_code = f" {course.code}"
            return (
                f"A{a_id}{course_code} "
                f"(W{int(info['week'])} {info['day']} S{int(info['slot']) + 1})"
            )
        return f"A{a_id}"

    def _clone_schedule(
        self, schedule: Dict[int, Dict[str, Any]] | None = None
    ) -> Dict[int, Dict[str, Any]]:
        source = self.current_schedule if schedule is None else schedule
        return {a_id: info.copy() for a_id, info in source.items()}

    def _invalidate_held_analysis_cache(self) -> None:
        self._held_analysis_cache_key = None
        self._held_analysis_cache_value = {}

    def _bump_schedule_revision(self) -> None:
        self._schedule_revision = int(self._schedule_revision) + 1
        self._invalidate_held_analysis_cache()
        self._conflict_ids_cache_revision = -1
        self._conflict_ids_cache = set()

    def _schedule_cache_token(
        self, schedule: Dict[int, Dict[str, Any]]
    ) -> Tuple[str, Any]:
        if schedule is self.current_schedule:
            return ("current", int(self._schedule_revision))
        return ("override", id(schedule))

    def _set_manual_highlight_base(
        self, schedule: Dict[int, Dict[str, Any]] | None = None
    ) -> None:
        if schedule is None:
            self._manual_highlight_base_schedule = {}
            return
        self._manual_highlight_base_schedule = {
            int(a_id): dict(info)
            for a_id, info in schedule.items()
            if isinstance(info, dict)
        }

    def _compute_soft_penalty(self, schedule: Dict[int, Dict[str, Any]]) -> int | None:
        if self.inst is None:
            return None
        try:
            if (
                self._soft_penalty_improver is None
                or self._soft_penalty_improver_inst_ref is not self.inst
            ):
                self._soft_penalty_improver = LocalSearchImprover(self.inst)
                self._soft_penalty_improver_inst_ref = self.inst
            return int(self._soft_penalty_improver.compute_soft_penalty(schedule))
        except Exception:
            return None

    def _format_score_status_suffix(self, before: int | None, after: int | None) -> str:
        if before is None or after is None:
            return ""
        delta = int(after) - int(before)
        return (
            f" | soft penalty {int(before)} -> {int(after)} "
            f"(Δ {delta:+d}, {self._describe_penalty_delta(delta)})"
        )

    def _show_improvement_delta_report(
        self,
        before_schedule: Dict[int, Dict[str, Any]],
        after_schedule: Dict[int, Dict[str, Any]],
        *,
        title: str = "Improvement report",
    ) -> None:
        if self.inst is None:
            return
        try:
            before = compute_penalty_breakdown(self.inst, before_schedule)
            after = compute_penalty_breakdown(self.inst, after_schedule)
        except Exception:
            return
        rows: List[Tuple[str, int, int, int]] = []
        for term in sorted(set(before.keys()) | set(after.keys())):
            if term == "total":
                continue
            b = int(before.get(term, 0))
            a = int(after.get(term, 0))
            if b != a:
                rows.append((str(term), b, a, int(a - b)))
        rows.sort(key=lambda row: (row[3], row[0]))
        moved = sum(
            1
            for a_id, info in after_schedule.items()
            if dict(before_schedule.get(int(a_id), {})) != dict(info)
        )
        lines = [
            f"Global soft penalty: {int(before.get('total', 0))} -> {int(after.get('total', 0))}",
            f"Delta: {int(after.get('total', 0)) - int(before.get('total', 0)):+d}",
            f"Moved activities: {int(moved)}",
            "",
            "Changed penalty terms:",
        ]
        if rows:
            for term, b, a, delta in rows[:12]:
                lines.append(f"- {term}: {b} -> {a} ({delta:+d})")
        else:
            lines.append("- No modeled soft-penalty terms changed.")
        QMessageBox.information(self, str(title), "\n".join(lines))

    def _sync_instance_staff_from_schedule(
        self, schedule: Dict[int, Dict[str, Any]]
    ) -> None:
        if self.inst is None:
            return
        for a_id, info in schedule.items():
            act = self.inst.activities.get(a_id)
            if act is None:
                continue
            try:
                sid = int(info["staff_id"])
            except Exception:
                continue
            if act.kind == "LEC":
                act.prof_id = sid
            else:
                act.ta_id = sid

    def _sync_instance_activity_weeks_from_schedule(
        self, schedule: Dict[int, Dict[str, Any]]
    ) -> None:
        if self.inst is None:
            return
        for a_id, info in schedule.items():
            act = self.inst.activities.get(int(a_id))
            if act is None:
                continue
            try:
                act.week = int(info.get("week", act.week))
            except Exception:
                continue

    def _touch_time_lock_if_present(self, a_id: int, day: str, slot: int) -> None:
        fixed = self.locked_activities.get(int(a_id))
        if not isinstance(fixed, dict):
            return
        if "day" in fixed and "slot" in fixed:
            fixed["day"] = str(day)
            fixed["slot"] = int(slot)
            self.locked_activities[int(a_id)] = fixed

    def _current_week(self) -> int | None:
        week_data = self.week_combo.currentData()
        if week_data is None:
            return None
        return int(week_data)

    def _cell_activity_ids_for_view(self, day: str, slot: int, week: int) -> List[int]:
        if self.inst is None or not self.current_schedule:
            return []
        view_type = self.view_type_combo.currentText()
        data = self.entity_combo.currentData()
        if data is None and view_type != "All":
            return []
        entity_id = int(data) if data is not None and view_type != "All" else None
        act_ids: List[int] = []
        for a_id, info in self.current_schedule.items():
            if int(info["week"]) != int(week):
                continue
            if str(info["day"]) != str(day):
                continue
            s0 = int(info["slot"])
            dur = int(info["duration"])
            if slot < s0 or slot >= s0 + dur:
                continue
            if view_type == "Group" and entity_id is not None and entity_id not in info["group_ids"]:
                continue
            if view_type == "Staff" and entity_id is not None and entity_id != int(info["staff_id"]):
                continue
            if view_type == "Room" and entity_id is not None and entity_id != int(info["room_id"]):
                continue
            act_ids.append(int(a_id))
        return act_ids

    def _selected_activity_ids_from_table_selection(self) -> List[int]:
        if self.inst is None:
            return []
        out: List[int] = []
        seen: Set[int] = set()
        for item in self.table.selectedItems():
            row = int(item.row())
            col = int(item.column())
            for a_id in self._cell_activity_map.get((row, col), []):
                if int(a_id) in seen:
                    continue
                seen.add(int(a_id))
                out.append(int(a_id))
        return out

    def _is_activity_changed_from_base(self, a_id: int) -> bool:
        current = self.current_schedule.get(int(a_id))
        base = self._manual_highlight_base_schedule.get(int(a_id))
        if current is None:
            return False
        if base is None:
            return True
        for key in ("week", "day", "slot", "room_id", "staff_id"):
            if current.get(key) != base.get(key):
                return True
        return False

    def _compute_conflicting_activity_ids(
        self, schedule: Dict[int, Dict[str, Any]]
    ) -> Set[int]:
        out: Set[int] = set()
        if self.inst is None:
            return out
        try:
            if schedule is self.current_schedule:
                errors = self._collect_conflict_errors()
            else:
                errors = validate_schedule_against_instance(
                    self.inst, schedule, strict_rooms=True, require_all_activities=True
                )
        except Exception:
            errors = []
        for err in errors:
            for match in re.findall(r"\bA(\d+)\b", str(err)):
                try:
                    out.add(int(match))
                except Exception:
                    continue
        return out

    def _choose_activity_from_ids(self, act_ids: List[int], title: str) -> int | None:
        if not act_ids:
            return None
        if len(act_ids) == 1:
            return int(act_ids[0])
        labels = [self._activity_title(a_id) for a_id in act_ids]
        choice, ok = QInputDialog.getItem(
            self,
            title,
            "Activity:",
            labels,
            0,
            False,
        )
        if not ok:
            return None
        idx = labels.index(choice)
        return int(act_ids[idx])

    def _set_held_activity(self, a_id: int) -> None:
        if a_id not in self.current_schedule:
            return
        self.held_activity_id = int(a_id)
        self._invalidate_held_analysis_cache()
        held_week = int(self.current_schedule[a_id]["week"])
        idx = self.week_combo.findData(held_week)
        if idx >= 0:
            self.week_combo.setCurrentIndex(idx)
        info = self.current_schedule[a_id]
        if self.inst is not None and str(info["day"]) in self.inst.days:
            self.selected_cell_row = self.inst.days.index(str(info["day"]))
            self.selected_cell_col = int(info["slot"])
            self.selected_activity_id = int(a_id)
        self.update_table()
        self._refresh_quick_actions()
        self.set_status(
            f"Holding {self._activity_title(a_id)}. Hover slots to inspect conflicts, then use 'Move Held Here'."
        )

    def _clear_held_activity(self) -> None:
        if self.held_activity_id is None:
            return
        held = self.held_activity_id
        self.held_activity_id = None
        self._invalidate_held_analysis_cache()
        self.update_table()
        self._refresh_quick_actions()
        self.set_status(f"Released held activity A{held}")

    def _collect_held_target_map(
        self,
        week: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> Dict[Tuple[str, int], bool]:
        analysis_map = self._build_held_move_analysis(
            week,
            schedule_override=schedule_override,
            compute_scores=False,
            include_conflicts=False,
        )
        return {
            key: bool(info.get("ok", False)) for key, info in analysis_map.items()
        }

    def _build_held_move_analysis(
        self,
        week: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
        *,
        compute_scores: bool = True,
        include_conflicts: bool = True,
    ) -> Dict[Tuple[str, int], Dict[str, Any]]:
        inst = self.inst
        if inst is None or self.held_activity_id is None:
            return {}
        schedule = self.current_schedule if schedule_override is None else schedule_override
        a_id = int(self.held_activity_id)
        info = schedule.get(a_id)
        if info is None:
            return {}
        origin_week = int(info["week"])
        current_day = str(info["day"])
        current_slot = int(info["slot"])
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        cache_key = (
            self._schedule_cache_token(schedule),
            int(a_id),
            int(week),
            int(origin_week),
            str(current_day),
            int(current_slot),
            int(room_id),
            int(staff_id),
            int(bool(compute_scores)),
            int(bool(include_conflicts)),
        )
        if self._held_analysis_cache_key == cache_key:
            return self._held_analysis_cache_value
        analysis = self._compute_held_move_analysis_snapshot(
            week,
            schedule_override=schedule,
            compute_scores=compute_scores,
            include_conflicts=include_conflicts,
        )
        self._held_analysis_cache_key = cache_key
        self._held_analysis_cache_value = analysis
        return analysis

    def _compute_held_move_analysis_snapshot(
        self,
        week: int,
        *,
        schedule_override: Dict[int, Dict[str, Any]],
        compute_scores: bool,
        include_conflicts: bool,
    ) -> Dict[Tuple[str, int], Dict[str, Any]]:
        inst = self.inst
        if inst is None or self.held_activity_id is None:
            return {}
        schedule = schedule_override
        a_id = int(self.held_activity_id)
        info = schedule.get(a_id)
        if info is None:
            return {}
        origin_week = int(info["week"])
        current_day = str(info["day"])
        current_slot = int(info["slot"])
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        base_penalty = self._compute_soft_penalty(schedule) if compute_scores else None
        analysis: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for day in inst.days:
            for slot in range(inst.slots_per_day):
                ok, reason = self.check_move(
                    a_id,
                    str(day),
                    int(slot),
                    room_id,
                    staff_id,
                    int(week),
                    schedule_override=schedule,
                )
                day_slot = (str(day), int(slot))
                details: Dict[str, Any] = {
                    "ok": bool(ok),
                    "reason": "",
                    "conflicts": [] if include_conflicts else None,
                    "score_current": base_penalty,
                    "score_after": None,
                    "score_delta": None,
                }
                if ok:
                    if compute_scores and base_penalty is not None:
                        if (
                            int(week) == int(origin_week)
                            and str(day) == current_day
                            and int(slot) == current_slot
                        ):
                            target_penalty = int(base_penalty)
                        else:
                            moved = self._clone_schedule(schedule)
                            moved[a_id]["week"] = int(week)
                            moved[a_id]["day"] = str(day)
                            moved[a_id]["slot"] = int(slot)
                            target_penalty = self._compute_soft_penalty(moved)
                        if target_penalty is not None:
                            details["score_after"] = int(target_penalty)
                            details["score_delta"] = int(target_penalty) - int(base_penalty)
                    analysis[day_slot] = details
                    continue
                details["reason"] = str(reason or "")
                if include_conflicts:
                    details["conflicts"] = self._find_move_conflicts(
                        a_id,
                        str(day),
                        int(slot),
                        room_id,
                        staff_id,
                        int(week),
                        schedule_override=schedule,
                    )
                analysis[day_slot] = details
        return analysis

    def _request_held_move_analysis_async(
        self,
        week: int,
        *,
        compute_scores: bool,
        include_conflicts: bool,
    ) -> None:
        if self.inst is None or self.held_activity_id is None:
            return
        schedule_snapshot = self._clone_schedule()
        a_id = int(self.held_activity_id)
        info = schedule_snapshot.get(a_id)
        if info is None:
            return
        key = (
            self._schedule_cache_token(schedule_snapshot),
            int(a_id),
            int(week),
            int(info["week"]),
            str(info["day"]),
            int(info["slot"]),
            int(info["room_id"]),
            int(info["staff_id"]),
            int(bool(compute_scores)),
            int(bool(include_conflicts)),
        )
        if self._held_analysis_async_key == key or self._held_analysis_cache_key == key:
            return
        self._held_analysis_async_key = key
        worker = FunctionWorker(
            self._compute_held_move_analysis_snapshot,
            int(week),
            schedule_override=schedule_snapshot,
            compute_scores=bool(compute_scores),
            include_conflicts=bool(include_conflicts),
        )

        def _on_done(result: object) -> None:
            if self._held_analysis_async_key != key:
                return
            if isinstance(result, dict):
                self._held_analysis_cache_key = key
                self._held_analysis_cache_value = {
                    (str(day), int(slot)): dict(details)
                    for (day, slot), details in result.items()
                }
                self._held_move_analysis_map = self._held_analysis_cache_value
                self._held_analysis_async_key = None
                self.update_table()

        def _on_error(_message: str) -> None:
            if self._held_analysis_async_key == key:
                self._held_analysis_async_key = None

        worker.signals.finished.connect(_on_done)
        worker.signals.error.connect(_on_error)
        self._thread_pool.start(worker)

    def _held_move_analysis_from_cache(
        self,
        week: int,
        *,
        compute_scores: bool,
        include_conflicts: bool,
    ) -> Dict[Tuple[str, int], Dict[str, Any]]:
        if self.inst is None or self.held_activity_id is None:
            return {}
        schedule = self.current_schedule
        a_id = int(self.held_activity_id)
        info = schedule.get(a_id)
        if info is None:
            return {}
        key = (
            self._schedule_cache_token(schedule),
            int(a_id),
            int(week),
            int(info["week"]),
            str(info["day"]),
            int(info["slot"]),
            int(info["room_id"]),
            int(info["staff_id"]),
            int(bool(compute_scores)),
            int(bool(include_conflicts)),
        )
        if self._held_analysis_cache_key == key:
            return dict(self._held_analysis_cache_value or {})
        return {}

    def _ensure_held_analysis_conflicts(
        self,
        *,
        day: str,
        slot: int,
        week: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        analysis = self._held_move_analysis_map.get((str(day), int(slot)))
        if analysis is None or bool(analysis.get("ok", False)):
            return []
        existing = analysis.get("conflicts")
        if isinstance(existing, list):
            return existing
        if self.held_activity_id is None:
            return []
        schedule = self.current_schedule if schedule_override is None else schedule_override
        info = schedule.get(int(self.held_activity_id))
        if info is None:
            return []
        conflicts = self._find_move_conflicts(
            int(self.held_activity_id),
            str(day),
            int(slot),
            int(info["room_id"]),
            int(info["staff_id"]),
            int(week),
            schedule_override=schedule,
        )
        analysis["conflicts"] = list(conflicts)
        return conflicts

    def _build_cell_tooltip(
        self,
        *,
        row: int,
        col: int,
        ids: List[int],
        week: int,
        day: str,
        held_id: int | None,
        held_week_ok: bool,
    ) -> str:
        lines: List[str] = [f"Week {week} | {day} S{int(col) + 1}"]
        if ids:
            lines.append("Activities:")
            for a_id in ids[:12]:
                note = ""
                info = self.current_schedule.get(int(a_id), {})
                raw_note = str(info.get("admin_note", "") or "").strip()
                if raw_note:
                    note = f" | note: {raw_note}"
                lines.append(f"  - {self._activity_title(int(a_id))}{note}")
            extra = len(ids) - 12
            if extra > 0:
                lines.append(f"  - ... +{extra} more")
        else:
            lines.append("Activities: none")

        if held_week_ok and held_id is not None:
            if held_id in ids:
                lines.append("")
                lines.append("Held activity origin slot.")
            else:
                analysis = self._held_move_analysis_map.get((str(day), int(col)))
                if analysis is not None:
                    lines.append("")
                    if bool(analysis.get("ok", False)):
                        lines.append("Hold move: valid target")
                        current_score = analysis.get("score_current")
                        target_score = analysis.get("score_after")
                        score_delta = analysis.get("score_delta")
                        if isinstance(current_score, int):
                            lines.append(f"Current soft penalty: {int(current_score)}")
                        if isinstance(target_score, int) and isinstance(score_delta, int):
                            lines.append(
                                f"If moved here: {int(target_score)} "
                                f"(Δ {int(score_delta):+d}, {self._describe_penalty_delta(int(score_delta))})"
                            )
                    else:
                        lines.append(
                            f"Hold move: blocked ({str(analysis.get('reason') or 'constraint violation')})"
                        )
                        current_score = analysis.get("score_current")
                        if isinstance(current_score, int):
                            lines.append(f"Current soft penalty: {int(current_score)}")
                        conflicts = analysis.get("conflicts")
                        if not isinstance(conflicts, list):
                            conflicts = self._ensure_held_analysis_conflicts(
                                day=str(day),
                                slot=int(col),
                                week=int(week),
                            )
                        if conflicts:
                            lines.append("Conflicts if moved here:")
                            for conflict in conflicts[:8]:
                                b_id = int(conflict.get("activity_id", -1))
                                reasons = ",".join(conflict.get("reasons", []))
                                lines.append(f"  - A{b_id} [{reasons}]")
                            extra = len(conflicts) - 8
                            if extra > 0:
                                lines.append(f"  - ... +{extra} more")

        return "\n".join(lines)

    def _find_move_conflicts(
        self,
        a_id: int,
        new_day: str,
        new_slot: int,
        new_room_id: int,
        new_staff_id: int,
        target_week: int | None = None,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> List[Dict[str, Any]]:
        schedule = self.current_schedule if schedule_override is None else schedule_override
        info = schedule.get(a_id)
        if info is None:
            return []
        week = int(info["week"]) if target_week is None else int(target_week)
        dur = int(info["duration"])
        groups = set(int(g) for g in info["group_ids"])
        target_slots = set(range(int(new_slot), int(new_slot) + dur))
        conflicts: List[Dict[str, Any]] = []
        for b_id, other in schedule.items():
            if int(b_id) == int(a_id):
                continue
            if int(other["week"]) != int(week) or str(other["day"]) != str(new_day):
                continue
            other_slots = set(
                range(int(other["slot"]), int(other["slot"]) + int(other["duration"]))
            )
            if not (target_slots & other_slots):
                continue
            reasons: List[str] = []
            if int(other["staff_id"]) == int(new_staff_id):
                reasons.append("staff")
            if int(other["room_id"]) == int(new_room_id):
                reasons.append("room")
            if groups & set(int(g) for g in other["group_ids"]):
                reasons.append("group")
            if reasons:
                conflicts.append(
                    {
                        "activity_id": int(b_id),
                        "reasons": reasons,
                    }
                )
        conflicts.sort(key=lambda item: int(item["activity_id"]))
        return conflicts

    def _find_relocation_slots(
        self,
        a_id: int,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
        *,
        week: int | None = None,
        limit: int = 20,
        exclude_starts: Set[Tuple[str, int]] | None = None,
    ) -> List[Tuple[str, int]]:
        inst = self.inst
        if inst is None:
            return []
        schedule = self.current_schedule if schedule_override is None else schedule_override
        info = schedule.get(int(a_id))
        if info is None:
            return []
        target_week = int(info["week"]) if week is None else int(week)
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        options: List[Tuple[str, int]] = []
        excluded = set(exclude_starts or set())
        for day in inst.days:
            for slot in range(inst.slots_per_day):
                key = (str(day), int(slot))
                if key in excluded:
                    continue
                ok, _ = self.check_move(
                    int(a_id),
                    str(day),
                    int(slot),
                    room_id,
                    staff_id,
                    target_week,
                    schedule_override=schedule,
                )
                if ok:
                    options.append(key)
                    if len(options) >= int(limit):
                        return options
        return options

    def _commit_schedule(self, schedule: Dict[int, Dict[str, Any]], status: str) -> None:
        before_penalty = self._compute_soft_penalty(self.current_schedule)
        after_penalty = self._compute_soft_penalty(schedule)
        self.current_schedule = {a_id: info.copy() for a_id, info in schedule.items()}
        if self._active_branch_name and self._active_branch_name in self._branches:
            self._branches[self._active_branch_name] = update_branch(
                self._branches[self._active_branch_name], self.current_schedule
            )
        self._bump_schedule_revision()
        self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status(status + self._format_score_status_suffix(before_penalty, after_penalty))
        self._refresh_history_buttons()
        self._append_audit_log(
            "schedule_commit",
            {
                "status": str(status),
                "before_soft_penalty": before_penalty,
                "after_soft_penalty": after_penalty,
                "activities": int(len(self.current_schedule)),
            },
        )
        self._save_persistent_history()

    def _attempt_swap_timeslots(self, a_id: int, b_id: int) -> Tuple[bool, str]:
        if a_id not in self.current_schedule or b_id not in self.current_schedule:
            return False, "Activity not found in schedule."
        schedule = self._clone_schedule()
        a = schedule[a_id]
        b = schedule[b_id]
        a_week, a_day, a_slot = int(a["week"]), str(a["day"]), int(a["slot"])
        b_week, b_day, b_slot = int(b["week"]), str(b["day"]), int(b["slot"])
        a["week"], a["day"], a["slot"] = b_week, b_day, b_slot
        b["week"], b["day"], b["slot"] = a_week, a_day, a_slot

        ok_a, reason_a = self.check_move(
            int(a_id),
            str(a["day"]),
            int(a["slot"]),
            int(a["room_id"]),
            int(a["staff_id"]),
            int(a["week"]),
            schedule_override=schedule,
        )
        if not ok_a:
            return False, f"Swap invalid for A{a_id}: {reason_a}"
        ok_b, reason_b = self.check_move(
            int(b_id),
            str(b["day"]),
            int(b["slot"]),
            int(b["room_id"]),
            int(b["staff_id"]),
            int(b["week"]),
            schedule_override=schedule,
        )
        if not ok_b:
            return False, f"Swap invalid for A{b_id}: {reason_b}"
        errors = self._validate_schedule_hard_errors(schedule, require_all=True)
        if errors:
            return False, f"Swap leaves {len(errors)} hard conflicts."

        self._push_undo_state()
        self._touch_time_lock_if_present(a_id, str(a["day"]), int(a["slot"]))
        self._touch_time_lock_if_present(b_id, str(b["day"]), int(b["slot"]))
        self._commit_schedule(
            schedule,
            f"Swapped {self._activity_title(a_id, schedule)} and {self._activity_title(b_id, schedule)}",
        )
        return True, ""

    def _attempt_relocate_conflict(
        self,
        held_id: int,
        conflict_id: int,
        held_day: str,
        held_slot: int,
        conflict_day: str,
        conflict_slot: int,
    ) -> Tuple[bool, str]:
        if held_id not in self.current_schedule or conflict_id not in self.current_schedule:
            return False, "Activity not found in schedule."
        schedule = self._clone_schedule()
        schedule[held_id]["day"] = str(held_day)
        schedule[held_id]["slot"] = int(held_slot)
        schedule[conflict_id]["day"] = str(conflict_day)
        schedule[conflict_id]["slot"] = int(conflict_slot)

        ok_held, reason_held = self.check_move(
            held_id,
            str(schedule[held_id]["day"]),
            int(schedule[held_id]["slot"]),
            int(schedule[held_id]["room_id"]),
            int(schedule[held_id]["staff_id"]),
            schedule_override=schedule,
        )
        if not ok_held:
            return False, f"Held move still invalid: {reason_held}"
        ok_conflict, reason_conflict = self.check_move(
            conflict_id,
            str(schedule[conflict_id]["day"]),
            int(schedule[conflict_id]["slot"]),
            int(schedule[conflict_id]["room_id"]),
            int(schedule[conflict_id]["staff_id"]),
            schedule_override=schedule,
        )
        if not ok_conflict:
            return False, f"Conflict relocation invalid: {reason_conflict}"
        errors = self._validate_schedule_hard_errors(schedule, require_all=True)
        if errors:
            return False, f"Plan leaves {len(errors)} hard conflicts."

        self._push_undo_state()
        self._touch_time_lock_if_present(held_id, str(held_day), int(held_slot))
        self._touch_time_lock_if_present(
            conflict_id, str(conflict_day), int(conflict_slot)
        )
        self._commit_schedule(
            schedule,
            f"Moved {self._activity_title(held_id, schedule)} and relocated {self._activity_title(conflict_id, schedule)}",
        )
        return True, ""

    def _commit_held_plan_move(
        self,
        held_id: int,
        target_week: int,
        target_day: str,
        target_slot: int,
        schedule: Dict[int, Dict[str, Any]],
        *,
        forced: bool = False,
    ) -> None:
        errors = self._validate_schedule_hard_errors(schedule, require_all=True)

        self._push_undo_state()
        self._touch_time_lock_if_present(held_id, str(target_day), int(target_slot))
        title = self._activity_title(held_id, schedule)
        status = f"Moved {title} to week {int(target_week)}"
        if forced:
            status += " (forced)"
        if errors:
            status += f" with {len(errors)} hard conflict(s)"
        self._commit_schedule(schedule, status)
        if forced and errors:
            QMessageBox.warning(
                self,
                "Forced move applied",
                "Move committed with unresolved hard conflicts.\n"
                "Use Conflicts to inspect and resolve remaining overlaps.",
            )

    def _resolve_held_move_conflicts(
        self,
        held_id: int,
        target_day: str,
        target_slot: int,
        target_week: int,
    ) -> None:
        info = self.current_schedule.get(int(held_id))
        if info is None or self.inst is None:
            return

        origin_week = int(info["week"])
        origin_day = str(info["day"])
        origin_slot = int(info["slot"])
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])

        planned = self._clone_schedule()
        planned[held_id]["week"] = int(target_week)
        planned[held_id]["day"] = str(target_day)
        planned[held_id]["slot"] = int(target_slot)
        step_note = ""
        dlg: MoveConflictDialog | None = None

        while True:
            conflicts = self._find_move_conflicts(
                held_id,
                str(target_day),
                int(target_slot),
                room_id,
                staff_id,
                int(target_week),
                schedule_override=planned,
            )
            if not conflicts:
                self._commit_held_plan_move(
                    held_id,
                    int(target_week),
                    str(target_day),
                    int(target_slot),
                    planned,
                    forced=False,
                )
                return

            relocation_options: Dict[int, List[Tuple[str, int]]] = {}
            for conflict in conflicts:
                b_id = int(conflict["activity_id"])
                b_info = planned.get(b_id)
                if b_info is None:
                    relocation_options[b_id] = []
                    continue
                relocation_options[b_id] = self._find_relocation_slots(
                    b_id,
                    schedule_override=planned,
                    exclude_starts={
                        (str(b_info["day"]), int(b_info["slot"])),
                        (str(target_day), int(target_slot)),
                    },
                )

            if dlg is None:
                dlg = MoveConflictDialog(
                    self,
                    self.inst,
                    planned,
                    held_id,
                    str(target_day),
                    int(target_slot),
                    conflicts,
                    relocation_options,
                )
            else:
                dlg.update_state(
                    conflicts,
                    relocation_options,
                    message=step_note
                    or f"{len(conflicts)} conflict(s) remain for held move.",
                )

            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            decision = dlg.get_decision()
            if not decision:
                return

            kind = str(decision[0])
            if kind == "force":
                approval = self._require_approval(
                    action="force_move_with_conflicts",
                    details={
                        "held_activity_id": int(held_id),
                        "target_week": int(target_week),
                        "target_day": str(target_day),
                        "target_slot": int(target_slot),
                        "conflict_count": int(len(conflicts)),
                    },
                )
                if approval is None:
                    step_note = "Force move canceled: approval not granted."
                    continue
                planned[held_id]["override_approval"] = dict(approval)
                self._commit_held_plan_move(
                    held_id,
                    int(target_week),
                    str(target_day),
                    int(target_slot),
                    planned,
                    forced=True,
                )
                return

            if kind == "swap":
                b_id = int(decision[1])
                b_info = planned.get(b_id)
                if b_info is None:
                    step_note = f"Selected conflict A{b_id} no longer exists."
                    continue
                prev_day = str(b_info["day"])
                prev_slot = int(b_info["slot"])
                prev_week = int(b_info["week"])
                b_info["week"] = int(origin_week)
                b_info["day"] = str(origin_day)
                b_info["slot"] = int(origin_slot)
                ok_b, reason_b = self.check_move(
                    int(b_id),
                    str(b_info["day"]),
                    int(b_info["slot"]),
                    int(b_info["room_id"]),
                    int(b_info["staff_id"]),
                    int(origin_week),
                    schedule_override=planned,
                )
                if not ok_b:
                    b_info["week"] = prev_week
                    b_info["day"] = prev_day
                    b_info["slot"] = prev_slot
                    step_note = f"Swap blocked for A{b_id}: {reason_b}"
                else:
                    step_note = (
                        f"Swapped conflict A{b_id} to held activity origin "
                        f"({origin_day} S{origin_slot + 1})."
                    )
                continue

            if kind == "relocate":
                b_id = int(decision[1])
                b_day = str(decision[2])
                b_slot = int(decision[3])
                b_info = planned.get(b_id)
                if b_info is None:
                    step_note = f"Selected conflict A{b_id} no longer exists."
                    continue
                prev_day = str(b_info["day"])
                prev_slot = int(b_info["slot"])
                prev_week = int(b_info["week"])
                b_info["day"] = str(b_day)
                b_info["slot"] = int(b_slot)
                ok_b, reason_b = self.check_move(
                    int(b_id),
                    str(b_day),
                    int(b_slot),
                    int(b_info["room_id"]),
                    int(b_info["staff_id"]),
                    int(prev_week),
                    schedule_override=planned,
                )
                if not ok_b:
                    b_info["week"] = prev_week
                    b_info["day"] = prev_day
                    b_info["slot"] = prev_slot
                    step_note = f"Relocation blocked for A{b_id}: {reason_b}"
                else:
                    step_note = f"Relocated conflict A{b_id} to {b_day} S{b_slot + 1}."
                continue

            step_note = f"Unknown action: {kind}"

    def _attempt_move_held_to(
        self, target_day: str, target_slot: int, target_week: int | None = None
    ) -> None:
        if self.inst is None or self.held_activity_id is None:
            return
        held_id = int(self.held_activity_id)
        if held_id not in self.current_schedule:
            self._clear_held_activity()
            return
        info = self.current_schedule[held_id]
        move_week = int(info["week"]) if target_week is None else int(target_week)
        room_id = int(info["room_id"])
        staff_id = int(info["staff_id"])
        cached_analysis = None
        current_week = self._current_week()
        if current_week is not None and int(current_week) == int(move_week):
            cached_analysis = self._held_move_analysis_map.get(
                (str(target_day), int(target_slot))
            )
        if isinstance(cached_analysis, dict):
            ok = bool(cached_analysis.get("ok", False))
            reason = str(cached_analysis.get("reason") or "")
        else:
            ok, reason = self.check_move(
                held_id,
                str(target_day),
                int(target_slot),
                room_id,
                staff_id,
                move_week,
            )
        if ok:
            schedule = self._clone_schedule()
            schedule[held_id]["week"] = int(move_week)
            schedule[held_id]["day"] = str(target_day)
            schedule[held_id]["slot"] = int(target_slot)
            self._push_undo_state()
            self._touch_time_lock_if_present(held_id, str(target_day), int(target_slot))
            self._commit_schedule(
                schedule,
                f"Moved {self._activity_title(held_id, schedule)}",
            )
            return

        conflicts = []
        if isinstance(cached_analysis, dict):
            conflicts = cached_analysis.get("conflicts")
            if not isinstance(conflicts, list):
                conflicts = self._ensure_held_analysis_conflicts(
                    day=str(target_day),
                    slot=int(target_slot),
                    week=int(move_week),
                )
        else:
            conflicts = self._find_move_conflicts(
                held_id,
                str(target_day),
                int(target_slot),
                room_id,
                staff_id,
                int(move_week),
            )
        if not conflicts:
            explanation = build_move_explanation_text(
                activity_id=int(held_id),
                target_week=int(move_week),
                target_day=str(target_day),
                target_slot=int(target_slot),
                valid=False,
                reason=str(reason),
                conflicts=[],
            )
            QMessageBox.warning(self, "Move blocked", explanation)
            return

        self._resolve_held_move_conflicts(
            held_id, str(target_day), int(target_slot), int(move_week)
        )

    def on_table_context_menu(self, pos) -> None:
        try:
            if self.inst is None or not self.current_schedule:
                return
            item = self.table.itemAt(pos)
            if item is None:
                return
            row = item.row()
            col = item.column()
            if row < 0 or col < 0:
                return
            week = self._current_week()
            if week is None:
                return
            day = self.inst.days[row]
            act_ids = list(self._cell_activity_map.get((row, col), []))

            menu = QMenu(self.table)
            act_hold = None
            act_edit = None
            act_toggle_time_lock = None
            act_toggle_room_lock = None
            act_swap_here = None
            if act_ids:
                act_hold = menu.addAction("Hold activity...")
                act_edit = menu.addAction("Edit activity...")
                act_toggle_time_lock = menu.addAction("Toggle time lock...")
                act_toggle_room_lock = menu.addAction("Toggle room lock...")
            act_move_held = None
            act_show_targets = None
            act_clear_held = None
            if self.held_activity_id is not None:
                menu.addSeparator()
                act_move_held = menu.addAction("Move held activity here")
                act_show_targets = menu.addAction("Show held move targets")
                if act_ids and int(self.held_activity_id) not in act_ids:
                    act_swap_here = menu.addAction("Swap held with activity here...")
                act_clear_held = menu.addAction("Release held activity")
            menu.addSeparator()
            act_show_conflicts = menu.addAction("Open conflict inspector")

            chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
            if chosen is None:
                return
            if chosen == act_hold:
                a_id = self._choose_activity_from_ids(act_ids, "Hold activity")
                if a_id is not None:
                    self._set_held_activity(a_id)
                return
            if chosen == act_edit:
                self.on_cell_double_clicked(row, col)
                return
            if chosen == act_toggle_time_lock:
                a_id = self._choose_activity_from_ids(act_ids, "Toggle time lock")
                if a_id is not None:
                    self._toggle_activity_lock(a_id, time_lock=True)
                return
            if chosen == act_toggle_room_lock:
                a_id = self._choose_activity_from_ids(act_ids, "Toggle room lock")
                if a_id is not None:
                    self._toggle_activity_lock(a_id, time_lock=False)
                return
            if chosen == act_move_held:
                self._attempt_move_held_to(str(day), int(col), int(week))
                return
            if chosen == act_swap_here:
                other_ids = [a for a in act_ids if a != int(self.held_activity_id)]
                b_id = self._choose_activity_from_ids(other_ids, "Swap with held activity")
                if b_id is not None and self.held_activity_id is not None:
                    ok_swap, reason_swap = self._attempt_swap_timeslots(
                        int(self.held_activity_id), int(b_id)
                    )
                    if not ok_swap:
                        QMessageBox.warning(self, "Swap blocked", reason_swap)
                return
            if chosen == act_show_targets:
                self._show_held_targets_dialog()
                return
            if chosen == act_clear_held:
                self._clear_held_activity()
                return
            if chosen == act_show_conflicts:
                self.on_show_conflicts()
                return
        except Exception:
            traceback.print_exc()
            self.set_status("Failed to open context actions")

    def on_sandbox_start(self) -> None:
        if not self.current_schedule:
            self.set_status("No schedule to branch")
            return
        self._sandbox_base_schedule = self._clone_schedule()
        self.set_status(
            "Sandbox branch started. Make edits, then use Sandbox Compare/Apply/Discard."
        )
        self._append_audit_log(
            "sandbox_started", {"activities": int(len(self._sandbox_base_schedule))}
        )

    def on_sandbox_compare(self) -> None:
        if self._sandbox_base_schedule is None:
            self.set_status("Start sandbox first")
            return
        summary = compare_schedules(self._sandbox_base_schedule, self.current_schedule)
        base_soft = self._compute_soft_penalty(self._sandbox_base_schedule)
        cur_soft = self._compute_soft_penalty(self.current_schedule)
        cur_hard = len(self._collect_conflict_errors()) if self.current_schedule else 0
        msg = [
            "Sandbox Comparison",
            f"Soft penalty: {base_soft} -> {cur_soft} (Δ {int((cur_soft or 0) - (base_soft or 0)):+d})",
            f"Hard conflicts now: {cur_hard}",
            f"Changed time: {summary.get('changed_time', 0)}",
            f"Changed room: {summary.get('changed_room', 0)}",
            f"Changed staff: {summary.get('changed_staff', 0)}",
        ]
        QMessageBox.information(self, "Sandbox Compare", "\n".join(msg))

    def on_sandbox_apply(self) -> None:
        if self._sandbox_base_schedule is None:
            self.set_status("No sandbox branch active")
            return
        if bool(self._protected_baseline.get("protected", False)):
            approval = self._require_approval(
                action="apply_branch_to_protected_baseline",
                details={"active_branch": self._active_branch_name},
            )
            if approval is None:
                self.set_status("Sandbox apply canceled: approval not granted")
                return
        sandbox_errors = self._validate_schedule_hard_errors(
            self.current_schedule, require_all=True
        )
        if sandbox_errors:
            sample = "\n".join(f"- {line}" for line in sandbox_errors[:10])
            QMessageBox.warning(
                self,
                "Sandbox apply blocked",
                "Current sandbox state has hard conflicts and cannot become base.\n\n"
                f"Conflicts: {len(sandbox_errors)}\n{sample}",
            )
            self.set_status(
                f"Sandbox apply blocked: {len(sandbox_errors)} hard conflicts"
            )
            return
        self.base_schedule = self._clone_schedule()
        self._set_manual_highlight_base(self.current_schedule)
        self._sandbox_base_schedule = None
        if self._active_branch_name and self._active_branch_name in self._branches:
            self._branches[self._active_branch_name] = update_branch(
                self._branches[self._active_branch_name], self.current_schedule
            )
        self.set_status("Sandbox branch applied as new base schedule.")
        self._append_audit_log("sandbox_applied", {"activities": int(len(self.base_schedule))})
        self._save_persistent_history()

    def on_sandbox_discard(self) -> None:
        if self._sandbox_base_schedule is None:
            self.set_status("No sandbox branch active")
            return
        self._push_undo_state()
        self.current_schedule = {
            int(a_id): info.copy()
            for a_id, info in self._sandbox_base_schedule.items()
        }
        self._sandbox_base_schedule = None
        self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self.update_table()
        self.update_quality_summary()
        self.set_status("Sandbox changes discarded; branch baseline restored.")
        self._append_audit_log("sandbox_discarded", {})

    def on_auto_repair_disruption(self) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule to repair")
            return
        disruption_type, ok = QInputDialog.getItem(
            self,
            "Auto-Repair Disruption",
            "Disruption type:",
            ["Staff outage (week)", "Room outage (week)"],
            0,
            False,
        )
        if not ok:
            return
        if not self.inst.weeks:
            self.set_status("Instance has no weeks configured")
            return
        week_labels = [f"W{int(w)}" for w in self.inst.weeks]
        week_choice, ok = QInputDialog.getItem(
            self,
            "Auto-Repair Disruption",
            "Affected week:",
            week_labels,
            0,
            False,
        )
        if not ok:
            return
        week = int(str(week_choice).lstrip("Ww").strip())
        prior_locks = {
            int(a_id): dict(lock)
            for a_id, lock in self.locked_activities.items()
            if isinstance(lock, dict)
        }
        updated = self._clone_schedule()
        affected: Set[int] = set()
        unresolved: Set[int] = set()

        if str(disruption_type).startswith("Staff"):
            options = []
            for sid, s in sorted(self.inst.staff.items()):
                options.append(f"{int(sid)}: {s.name}")
            choice, ok = QInputDialog.getItem(
                self,
                "Staff outage",
                "Unavailable staff:",
                options,
                0,
                False,
            )
            if not ok:
                return
            staff_id = int(str(choice).split(":", 1)[0].strip())
            staff = self.inst.staff.get(int(staff_id))
            if staff is not None:
                weeks = getattr(staff, "available_weeks", None)
                if weeks is None:
                    weeks = set(int(w) for w in self.inst.weeks)
                weeks = {int(w) for w in weeks if int(w) != int(week)}
                staff.available_weeks = weeks
            apply_staff = _window_global("apply_staff_outage_week", apply_staff_outage_week)
            updated, affected, unresolved = apply_staff(
                self.inst,
                updated,
                staff_id=int(staff_id),
                week=int(week),
            )
        else:
            options = []
            for rid, r in sorted(self.inst.rooms.items()):
                options.append(f"{int(rid)}: {r.name}")
            choice, ok = QInputDialog.getItem(
                self,
                "Room outage",
                "Unavailable room:",
                options,
                0,
                False,
            )
            if not ok:
                return
            room_id = int(str(choice).split(":", 1)[0].strip())
            apply_room = _window_global("apply_room_outage_week", apply_room_outage_week)
            updated, affected, unresolved = apply_room(
                self.inst,
                updated,
                room_id=int(room_id),
                week=int(week),
            )

        if not affected:
            self.set_status("No activities affected by selected disruption.")
            return
        self._push_undo_state()
        self._commit_schedule(
            updated,
            f"Applied disruption pre-repair for week {week} "
            f"(affected={len(affected)}, unresolved={len(unresolved)})",
        )
        build_locks = _window_global("build_freeze_locks", build_freeze_locks)
        freeze_locks = build_locks(
            self.current_schedule,
            unlocked_activity_ids=affected,
        )
        self.locked_activities = freeze_locks
        self._sync_locks_to_instance()
        self._restore_locks_after_solve = prior_locks
        self._append_audit_log(
            "auto_repair_started",
            {
                "type": str(disruption_type),
                "week": int(week),
                "affected": int(len(affected)),
                "unresolved": int(len(unresolved)),
            },
        )
        if unresolved:
            QMessageBox.warning(
                self,
                "Auto-repair warning",
                f"{len(unresolved)} activity(ies) had no direct replacement; solver will try to recover.",
            )
        self._start_solver_process(keep_locks=True)

    def on_show_conflicts(self) -> None:
        errors = self._collect_conflict_errors()
        if not errors:
            QMessageBox.information(
                self,
                "Conflict Inspector",
                "No hard conflicts detected in the current schedule.",
            )
            self.set_status("No hard conflicts")
            return
        friendly_errors = [self._humanize_conflict_error(err) for err in errors]
        dialog_cls = _window_global("ConflictInspectorDialog", ConflictInspectorDialog)
        dlg = dialog_cls(self, friendly_errors)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if dlg.solve_conflicts_requested():
                self._solve_current_conflicts(errors)
                return
            activity_id = dlg.selected_activity_id()
            if activity_id is not None:
                if self._jump_to_activity(int(activity_id)):
                    self.set_status(f"Jumped to conflict activity A{int(activity_id)}")
                else:
                    self.set_status(
                        f"Conflict selected: A{int(activity_id)} (unable to jump)"
                    )
                return
        self.set_status(f"Conflicts found: {len(errors)}")

    def _restore_locks_if_needed(self) -> None:
        if self._restore_locks_after_solve is None:
            return
        self.locked_activities = {
            int(a_id): dict(lock)
            for a_id, lock in self._restore_locks_after_solve.items()
            if isinstance(lock, dict)
        }
        self._restore_locks_after_solve = None
        self._sync_locks_to_instance()
        self._refresh_history_buttons()

    def on_clear_locks(self):
        if self.locked_activities:
            self._push_undo_state()
        self.locked_activities = {}
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status("Locks cleared")
        self._refresh_history_buttons()

    def on_cell_double_clicked(self, row: int, col: int):
        try:
            if self.inst is None or not self.current_schedule:
                return
            if self.entity_combo.count() == 0 or self.week_combo.count() == 0:
                return

            if self.entity_combo.currentData() is None:
                return

            week_data = self.week_combo.currentData()
            if week_data is None:
                return
            week = int(week_data)

            day = self.inst.days[row]
            slot = col

            act_ids = self._cell_activity_ids_for_view(day, slot, week)

            if not act_ids:
                return

            dlg = EditActivityDialog(
                self,
                self.inst,
                self.current_schedule,
                act_ids,
                week,
                day,
                slot,
                locked=self.locked_activities,
            )
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

            (
                a_id,
                new_week,
                new_day,
                new_slot,
                new_room,
                new_staff,
                lock_time,
                lock_room,
                admin_note,
            ) = dlg.get_values()
            ok, reason = self.check_move(
                a_id, new_day, new_slot, new_room, new_staff, int(new_week)
            )
            if not ok:
                QMessageBox.warning(self, "Invalid move", reason)
                return

            self._push_undo_state()
            updated_schedule = self._clone_schedule()
            info = updated_schedule[a_id]
            info["week"] = int(new_week)
            info["day"] = new_day
            info["slot"] = new_slot
            info["room_id"] = new_room
            info["staff_id"] = new_staff
            if str(admin_note).strip():
                info["admin_note"] = str(admin_note).strip()
            else:
                info.pop("admin_note", None)

            # Update locks (used by re-solve).
            fixed = dict(self.locked_activities.get(a_id, {}))
            if lock_time:
                fixed["day"] = new_day
                fixed["slot"] = int(new_slot)
            else:
                fixed.pop("day", None)
                fixed.pop("slot", None)
            if lock_room:
                fixed["room_id"] = int(new_room)
            else:
                fixed.pop("room_id", None)
            if fixed:
                self.locked_activities[a_id] = fixed
            else:
                self.locked_activities.pop(a_id, None)

            self._commit_schedule(
                updated_schedule, f"Edited A{a_id} (locks={len(self.locked_activities)})"
            )
        except Exception:
            traceback.print_exc()
            self.set_status("Edit failed")

    def check_move(
        self,
        a_id: int,
        new_day: str,
        new_slot: int,
        new_room_id: int,
        new_staff_id: int,
        new_week: int | None = None,
        schedule_override: Dict[int, Dict[str, Any]] | None = None,
    ) -> Tuple[bool, str]:
        inst = self.inst
        if inst is None:
            return False, "No instance loaded."
        schedule = self.current_schedule if schedule_override is None else schedule_override
        if a_id not in schedule:
            return False, f"Activity A{a_id} not found in schedule."
        if a_id not in inst.activities:
            return False, f"Activity A{a_id} not found in instance."
        if new_staff_id not in inst.staff:
            return False, "Unknown staff member."
        if new_room_id not in inst.rooms:
            return False, "Unknown room."
        act = inst.activities[a_id]
        info = schedule[a_id]
        try:
            w = int(info["week"]) if new_week is None else int(new_week)
        except Exception:
            return False, "Invalid week."
        week_set = {int(x) for x in inst.weeks}
        if int(w) not in week_set:
            return False, "Unknown week."
        dur = int(info["duration"])
        groups = info["group_ids"]
        group_set = {int(g) for g in groups}
        hard_flags = getattr(inst, "hard_constraints", {}) or {}

        def _flag(name: str, default: bool = True) -> bool:
            raw = hard_flags.get(name, default) if isinstance(hard_flags, dict) else default
            if isinstance(raw, bool):
                return raw
            if raw is None:
                return default
            return str(raw).strip().lower() not in ("0", "false", "no")

        def _is_block_staff(member: Any) -> bool:
            return bool(
                getattr(member, "blocks_only", False)
                or getattr(member, "prefers_block", False)
                or getattr(member, "is_block_prof", False)
            )

        if new_slot < 0 or new_slot + dur > inst.slots_per_day:
            return False, "Activity would overflow the day."

        if calendar_slot_blocked(inst, week=int(w), day=str(new_day)):
            return False, "Target day is blocked by calendar blackout/holiday rules."

        if _flag("week1_lectures_only", True) and inst.weeks:
            first_week = min(int(wk) for wk in inst.weeks)
            if int(w) == int(first_week) and act.kind in ("TUT", "LAB"):
                return False, "Week 1 allows lectures only."

        staff = inst.staff[new_staff_id]
        if act.kind == "LEC":
            if not staff.is_prof:
                return False, "Lectures must be taught by a professor."
            if act.course_id not in staff.can_teach_courses:
                return False, "Professor cannot teach this course."
        else:
            if staff.is_prof:
                return False, "Tutorials/labs must be taught by a TA."
            if act.course_id not in staff.can_teach_courses:
                return False, "TA cannot teach this course."
        if new_day not in staff.available_days:
            return False, "Staff unavailable on that day."
        allowed_weeks = getattr(staff, "available_weeks", None)
        if allowed_weeks is not None:
            allowed_week_set = {int(v) for v in allowed_weeks}
            if allowed_week_set and int(w) not in allowed_week_set:
                return False, "Staff unavailable in that week."

        day_load = 0
        week_load = 0
        for b_id, b in schedule.items():
            if b_id == a_id:
                continue
            if b["staff_id"] != new_staff_id:
                continue
            if int(b["week"]) == int(w):
                week_load += b["duration"]
                if b["day"] == new_day:
                    day_load += b["duration"]
        day_load += dur
        week_load += dur

        if _flag("enforce_staff_daily_caps", True) and staff.max_slots_per_day is not None and day_load > staff.max_slots_per_day:
            return False, "Staff daily load limit exceeded."
        if _flag("enforce_staff_weekly_caps", True) and staff.max_slots_per_week is not None and week_load > staff.max_slots_per_week:
            return False, "Staff weekly load limit exceeded."

        if _flag("enforce_block_professor_rules", True) and _is_block_staff(staff):
            teaching_days = {str(new_day)}
            for b_id, b in schedule.items():
                if int(b_id) == int(a_id):
                    continue
                if int(b["week"]) != int(w) or int(b["staff_id"]) != int(new_staff_id):
                    continue
                teaching_days.add(str(b["day"]))
            if len(teaching_days) > 2:
                return False, "Block-staff can teach on at most two days per week."

            if act.kind == "LEC" and bool(getattr(staff, "blocks_only", False)):
                slots_by_day: Dict[str, Set[int]] = {}
                total = 0
                for b_id, b in schedule.items():
                    if int(b_id) == int(a_id):
                        continue
                    if int(b["week"]) != int(w):
                        continue
                    if int(b["staff_id"]) != int(new_staff_id):
                        continue
                    other_act = inst.activities.get(int(b_id))
                    if other_act is None:
                        continue
                    if other_act.kind != "LEC" or int(other_act.course_id) != int(act.course_id):
                        continue
                    day_cur = str(b["day"])
                    slot_cur = int(b["slot"])
                    dur_cur = int(b["duration"])
                    total += dur_cur
                    day_slots = slots_by_day.setdefault(day_cur, set())
                    for off in range(dur_cur):
                        day_slots.add(slot_cur + off)
                total += int(dur)
                own_slots = slots_by_day.setdefault(str(new_day), set())
                for off in range(int(dur)):
                    own_slots.add(int(new_slot) + off)

                if total and not (2 <= total <= 3):
                    return False, "Block-only professor lectures must be 2-3 contiguous slots per course/week."
                if len(slots_by_day) > 1:
                    return False, "Block-only professor lectures for a course must stay on one day."
                for slots_for_day in slots_by_day.values():
                    sorted_slots = sorted(slots_for_day)
                    for idx in range(1, len(sorted_slots)):
                        if sorted_slots[idx] != sorted_slots[idx - 1] + 1:
                            return False, "Block-only professor lecture slots must be contiguous."

        room = inst.rooms[new_room_id]
        total_students = sum(inst.groups[int(g)].size for g in groups)
        if room.capacity < total_students:
            return False, "Room capacity too small."
        if not room_is_available(
            inst,
            int(new_room_id),
            week=int(w),
            day=str(new_day),
            start_slot=int(new_slot),
            dur=int(dur),
        ):
            return False, "Room unavailable at that day/slot."
        if not generic_resources_available(
            inst,
            getattr(act, "resource_ids", []) or [],
            day=str(new_day),
            start_slot=int(new_slot),
            dur=int(dur),
        ):
            return False, "Generic resource unavailable at that day/slot."

        if act.kind == "LAB":
            if room.room_type not in ("COMPUTER_LAB", "SPECIALIZED_LAB"):
                return False, "Lab must be in a lab room."
            if act.requires_specialization and act.requires_specialization not in room.specialization_tags:
                return False, "Wrong specialized lab."
        elif act.kind == "LEC":
            if room.room_type != "LECTURE":
                return False, "Lecture must use a lecture room."
        else:  # TUT
            if room.room_type not in ("LECTURE", "TUTORIAL"):
                return False, "Tutorial must use a lecture/tutorial room."

        if _flag("force_repeat_weekly_pattern", False) and inst.weeks:
            first_week = min(int(wk) for wk in inst.weeks)
            if int(w) != int(first_week):
                repeat_key = (
                    int(act.course_id),
                    str(act.kind),
                    int(new_staff_id),
                    tuple(sorted(int(g) for g in groups)),
                    int(dur),
                )
                for b_id, b in schedule.items():
                    if int(b_id) == int(a_id):
                        continue
                    other_act = inst.activities.get(int(b_id))
                    if other_act is None:
                        continue
                    if int(b.get("week", 0)) == int(first_week):
                        continue
                    other_key = (
                        int(other_act.course_id),
                        str(other_act.kind),
                        int(b.get("staff_id", -1)),
                        tuple(sorted(int(g) for g in (b.get("group_ids", []) or []))),
                        int(b.get("duration", 1)),
                    )
                    if other_key != repeat_key:
                        continue
                    if (
                        str(b.get("day")) != str(new_day)
                        or int(b.get("slot", -1)) != int(new_slot)
                        or int(b.get("room_id", -1)) != int(new_room_id)
                    ):
                        return (
                            False,
                            f"Repeat weekly pattern requires matching A{b_id} "
                            "to use the same day, slot, and room.",
                        )

        new_slots = set(range(int(new_slot), int(new_slot) + int(dur)))
        for b_id, b in schedule.items():
            if b_id == a_id:
                continue
            if int(b["week"]) != int(w) or b["day"] != new_day:
                continue
            other_slots = set(range(b["slot"], b["slot"] + b["duration"]))
            if not (new_slots & other_slots):
                continue
            if b["staff_id"] == new_staff_id:
                return False, f"Staff conflict with A{b_id}."
            if b["room_id"] == new_room_id:
                return False, f"Room conflict with A{b_id}."
            if any(int(g) in group_set for g in b["group_ids"]):
                return False, f"Group conflict with A{b_id}."

        trial = {int(k): dict(v) for k, v in schedule.items()}
        trial[int(a_id)] = {
            **trial[int(a_id)],
            "week": int(w),
            "day": str(new_day),
            "slot": int(new_slot),
            "room_id": int(new_room_id),
            "staff_id": int(new_staff_id),
        }
        precedence_errors = precedence_violations(inst, trial)
        if precedence_errors:
            return False, str(precedence_errors[0])
        travel_errors = travel_buffer_violations(inst, trial)
        if travel_errors:
            return False, str(travel_errors[0])
        resource_errors = generic_resource_violations(inst, trial)
        if resource_errors:
            return False, str(resource_errors[0])

        return True, ""
