from __future__ import annotations

from ui.window_runtime import *  # noqa: F401,F403


class WindowSolverMixin:

    def set_status(self, text: str):
        self._status_full_text = str(text)
        self._refresh_status_label()
        QApplication.processEvents()

    def _selected_improve_focus_term(self) -> str:
        if not hasattr(self, "improve_focus_combo"):
            return ""
        data = self.improve_focus_combo.currentData()
        term = str(data or "").strip()
        return term if term in SOFT_WEIGHT_DEFAULTS else ""

    def _build_focused_improve_instance(self, term: str) -> Instance:
        if self.inst is None:
            raise ValueError("No instance loaded")
        return build_focused_improve_instance(self.inst, term)

    def _refresh_status_label(self) -> None:
        full = str(getattr(self, "_status_full_text", "") or "")
        if not hasattr(self, "status_label"):
            return
        self.status_label.setToolTip(full)
        try:
            self.status_label.setText(self._compact_status_text(full))
        except Exception:
            self.status_label.setText(full)

    def set_busy(self, busy: bool):
        enable = not busy
        for btn in [
            self.generate_button,
            self.solve_button,
            self.clear_locks_button,
            self.improve_button,
            self.stop_improve_button,
            self.export_menu_btn,
            self.project_menu_btn,
            self.undo_button,
            self.redo_button,
            self.revert_button,
            self.conflicts_button,
        ]:
            btn.setEnabled(enable)
        self.improve_runs_spin.setEnabled(enable)
        self.ls_time_spin.setEnabled(enable)
        self.room_mode_combo.setEnabled(enable)
        self.objective_profile_combo.setEnabled(enable)
        self.objective_cb.setEnabled(enable)
        self.debug_diagnostics_cb.setEnabled(enable)
        self.time_limit_spin.setEnabled(enable)
        self.random_seed_spin.setEnabled(enable)
        self.workers_preset_combo.setEnabled(enable)
        self.workspace_tabs.setEnabled(enable)
        self.custom_reset_staff_btn.setEnabled(enable)
        self.custom_reset_rooms_btn.setEnabled(enable)
        self.custom_reset_programs_btn.setEnabled(enable)
        self.custom_reset_course_patterns_btn.setEnabled(enable)
        self.apply_constraints_btn.setEnabled(enable)
        # Keep stop available while a local improvement pass is running.
        if hasattr(self, "stop_improve_button"):
            self.stop_improve_button.setEnabled(bool(busy and self._improve_running))
        if enable:
            self._refresh_history_buttons()
            self._refresh_quick_actions()

    def _start_solve_progress(self) -> None:
        self._stop_solve_progress()
        self._solve_started_at = time.perf_counter()
        ctx = dict(self._solve_progress_context or {})
        phased = bool(ctx.get("phased", False))
        feasibility_seconds = float(ctx.get("feasibility_seconds", 0.0) or 0.0)
        improve_total_seconds = float(ctx.get("improve_total_seconds", 0.0) or 0.0)
        if phased:
            self._solve_expected_seconds = max(1.0, feasibility_seconds + improve_total_seconds)
        else:
            self._solve_expected_seconds = max(1.0, float(self.time_limit_spin.value()))
        self._solve_progress_percent = 0
        self._solve_attempt_started_at = None
        self._solve_progress_timer = QTimer(self)
        self._solve_progress_timer.setInterval(400)
        self._solve_progress_timer.timeout.connect(self._on_solve_progress_tick)
        self._solve_progress_timer.start()

    def _on_solve_progress_tick(self) -> None:
        if self.proc is None or self._solve_started_at is None:
            self._stop_solve_progress()
            return
        ctx = self._solve_progress_context or {}
        phased = bool(ctx.get("phased", False))
        attempt_idx = int(ctx.get("attempt", 1) or 1)
        expected_attempts = max(1, int(ctx.get("expected_attempts", 1) or 1))
        solve_share = 0.5 if phased else 1.0
        base_pct = int((max(0, attempt_idx - 1) / float(expected_attempts)) * (solve_share * 100.0))
        limit = float(ctx.get("attempt_limit_seconds", 0.0) or 0.0)
        if self._solve_attempt_started_at is not None and limit > 0:
            elapsed_attempt = max(0.0, time.perf_counter() - self._solve_attempt_started_at)
            frac_attempt = min(1.0, elapsed_attempt / max(1.0, limit))
            pct = int(base_pct + frac_attempt * ((solve_share * 100.0) / float(expected_attempts)))
        else:
            completed = max(0, int(ctx.get("completed_attempts", 0) or 0))
            pct = int((min(completed, expected_attempts) / float(expected_attempts)) * (solve_share * 100.0))
        phase_label = str(ctx.get("phase_label", "running"))
        self._update_solve_progress_status(pct, phase_label)

    def _update_solve_progress_status(self, pct: int, phase_label: str = "") -> None:
        pct_clamped = max(0, min(99, int(pct)))
        if pct_clamped < int(self._solve_progress_percent):
            pct_clamped = int(self._solve_progress_percent)
        self._solve_progress_percent = int(pct_clamped)
        detail = f" ({phase_label})" if str(phase_label).strip() else ""
        self._status_full_text = f"Solving... {int(self._solve_progress_percent)}%{detail}"
        self._refresh_status_label()

    def _stop_solve_progress(self) -> None:
        if self._solve_progress_timer is not None:
            self._solve_progress_timer.stop()
            self._solve_progress_timer.deleteLater()
        self._solve_progress_timer = None
        self._solve_started_at = None
        self._solve_expected_seconds = 0.0
        self._solve_progress_percent = 0
        self._solve_attempt_started_at = None
        self._solve_progress_context = {}
        self._solver_output_partial = ""

    def _expected_solver_attempts(self, *, phased: bool, room_mode: str, objective_on: bool) -> int:
        mode = str(room_mode)
        if phased:
            # Feasibility-first: room-mode attempt, then optional strict->greedy fallback.
            return 2 if mode == "cp_rooms" else 1
        attempts = 1
        if bool(objective_on):
            attempts += 1  # objective-off retry
        if mode == "cp_rooms":
            attempts += 1  # strict->greedy fallback
        return max(1, int(attempts))

    def _room_mode_selection(self) -> str:
        if not hasattr(self, "room_mode_combo") or self.room_mode_combo is None:
            return "cp_rooms"
        data = self.room_mode_combo.currentData()
        if str(data) in {"auto", "cp_rooms", "greedy"}:
            return str(data)
        text = str(self.room_mode_combo.currentText()).strip().lower()
        if "fast" in text or "greedy" in text:
            return "greedy"
        if "auto" in text:
            return "auto"
        return "cp_rooms"

    def _estimate_cp_room_candidate_count(self, inst: Any | None = None) -> int:
        inst = inst or self.inst
        if inst is None:
            return 0
        total = 0
        for act in inst.activities.values():
            kind = str(act.kind)
            need = sum(
                int(inst.groups[g_id].size)
                for g_id in act.group_ids
                if g_id in inst.groups
            )
            count = 0
            for room in inst.rooms.values():
                if int(room.capacity) < int(need):
                    continue
                room_type = str(room.room_type)
                if kind == "LEC":
                    if room_type == "LECTURE":
                        count += 1
                elif kind == "TUT":
                    if room_type in {"TUTORIAL", "LECTURE"}:
                        count += 1
                elif kind == "LAB":
                    tag = str(getattr(act, "requires_specialization", "") or "").strip()
                    if tag:
                        tags = set(getattr(room, "specialization_tags", []) or [])
                        if room_type == "SPECIALIZED_LAB" and tag in tags:
                            count += 1
                    elif room_type in {"COMPUTER_LAB", "SPECIALIZED_LAB"}:
                        count += 1
            total += int(count)
        return int(total)

    def _auto_room_mode_uses_greedy(self, inst: Any | None = None) -> bool:
        inst = inst or self.inst
        if inst is None:
            return False
        activity_count = len(getattr(inst, "activities", {}) or {})
        room_count = len(getattr(inst, "rooms", {}) or {})
        candidate_count = self._estimate_cp_room_candidate_count(inst)
        return (
            int(activity_count) >= 1000
            or int(room_count) >= 100
            or int(candidate_count) >= 50000
        )

    def _selected_room_mode(self) -> str:
        selection = self._room_mode_selection()
        if selection == "auto":
            return "greedy" if self._auto_room_mode_uses_greedy() else "cp_rooms"
        return selection

    def _selected_room_mode_label(self) -> str:
        selection = self._room_mode_selection()
        resolved = self._selected_room_mode()
        if selection == "auto":
            candidate_count = self._estimate_cp_room_candidate_count()
            return f"auto -> {resolved} (estimated CP room candidates={candidate_count})"
        return str(resolved)

    def _selected_worker_count(self) -> int:
        if hasattr(self, "workers_preset_combo") and self.workers_preset_combo is not None:
            data = self.workers_preset_combo.currentData()
            try:
                return max(1, min(64, int(data)))
            except Exception:
                pass
        return max(1, min(64, int(DEFAULT_CP_WORKERS)))

    def on_solver_output_ready(self) -> None:
        sender_proc = self.sender()
        if (
            sender_proc is not None
            and self.proc is not None
            and sender_proc is not self.proc
        ):
            return
        if self.proc is None:
            return
        try:
            chunk = bytes(self.proc.readAll()).decode("utf-8", errors="ignore")
        except Exception:
            return
        if not chunk:
            return
        self._solver_output_log += str(chunk)
        blob = self._solver_output_partial + str(chunk)
        lines = blob.splitlines()
        if blob and not blob.endswith("\n"):
            self._solver_output_partial = lines[-1] if lines else blob
            lines = lines[:-1]
        else:
            self._solver_output_partial = ""
        for raw in lines:
            line = str(raw).strip()
            if not line:
                continue
            if not line.startswith("[progress] "):
                continue
            payload = line[len("[progress] "):].strip()
            try:
                event = json.loads(payload)
            except Exception:
                continue
            if isinstance(event, dict):
                self._handle_solver_progress_event(event)

    def _handle_solver_progress_event(self, event: Dict[str, Any]) -> None:
        kind = str(event.get("event", "")).strip().lower()
        ctx = dict(self._solve_progress_context or {})
        phased = bool(ctx.get("phased", event.get("phased", False)))
        expected_attempts = max(1, int(ctx.get("expected_attempts", 1) or 1))
        if kind == "run_start":
            mode = str(event.get("room_mode", ctx.get("room_mode", "")))
            objective = bool(event.get("use_objective", ctx.get("objective_on", False)))
            phased = bool(event.get("phased", phased))
            expected_attempts = self._expected_solver_attempts(
                phased=bool(phased),
                room_mode=str(mode),
                objective_on=bool(objective),
            )
            ctx["phased"] = bool(phased)
            ctx["room_mode"] = str(mode)
            ctx["objective_on"] = bool(objective)
            ctx["expected_attempts"] = int(expected_attempts)
            ctx["completed_attempts"] = 0
            self._solve_progress_context = ctx
            return
        solve_share = 0.5 if phased else 1.0
        improve_share = 1.0 - solve_share

        if kind == "solve_attempt_start":
            attempt = max(1, int(event.get("attempt", 1) or 1))
            expected_attempts = max(expected_attempts, int(attempt))
            limit = event.get("limit_seconds")
            try:
                attempt_limit = float(limit) if limit is not None else float(self.time_limit_spin.value())
            except Exception:
                attempt_limit = float(self.time_limit_spin.value())
            ctx["attempt"] = int(attempt)
            ctx["expected_attempts"] = int(expected_attempts)
            ctx["completed_attempts"] = max(int(ctx.get("completed_attempts", 0) or 0), int(attempt - 1))
            ctx["attempt_limit_seconds"] = float(max(1.0, attempt_limit))
            mode = str(event.get("mode", ctx.get("room_mode", "")))
            objective = bool(event.get("objective", False))
            phase = "objective" if objective else "feasibility"
            mode_label = "strict cp_rooms" if mode == "cp_rooms" else "greedy"
            if mode == "greedy" and str(ctx.get("room_mode", "")) == "cp_rooms" and int(attempt) > 1:
                mode_label = "greedy fallback"
            ctx["phase_label"] = f"attempt {attempt}/{expected_attempts}: {mode_label} ({phase})"
            self._solve_progress_context = ctx
            self._solve_attempt_started_at = time.perf_counter()
            base_pct = int((max(0, attempt - 1) / float(expected_attempts)) * (solve_share * 100.0))
            self._update_solve_progress_status(base_pct, str(ctx.get("phase_label", "")))
            return

        if kind == "solve_attempt_done":
            attempt = max(1, int(event.get("attempt", ctx.get("attempt", 1)) or 1))
            expected_attempts = max(expected_attempts, int(attempt))
            ctx["attempt"] = int(attempt)
            ctx["expected_attempts"] = int(expected_attempts)
            ctx["completed_attempts"] = int(attempt)
            status = event.get("status")
            ctx["phase_label"] = f"attempt {attempt}/{expected_attempts} done (status {status})"
            self._solve_progress_context = ctx
            self._solve_attempt_started_at = None
            pct = int((min(attempt, expected_attempts) / float(expected_attempts)) * (solve_share * 100.0))
            self._update_solve_progress_status(pct, str(ctx.get("phase_label", "")))
            return

        if kind == "solve_fallback":
            from_mode = str(event.get("from_mode", "cp_rooms"))
            to_mode = str(event.get("to_mode", "greedy"))
            label = f"fallback: {from_mode} -> {to_mode}"
            ctx["phase_label"] = label
            self._solve_progress_context = ctx
            self._update_solve_progress_status(int(self._solve_progress_percent), label)
            return

        if kind == "improve_start":
            max_rounds = max(1, int(ctx.get("improve_max_rounds", event.get("max_rounds", 1)) or 1))
            ctx["phase_label"] = f"improve round 0/{max_rounds}"
            self._solve_progress_context = ctx
            self._update_solve_progress_status(
                int(solve_share * 100.0),
                str(ctx.get("phase_label", "improve round 0/1")),
            )
            return

        if kind == "improve_round":
            round_idx = max(0, int(event.get("round", 0) or 0))
            max_rounds = max(1, int(event.get("max_rounds", 1) or 1))
            elapsed = float(event.get("elapsed_seconds", 0.0) or 0.0)
            total = float(event.get("total_seconds", 0.0) or 0.0)
            frac_rounds = min(1.0, float(round_idx) / float(max_rounds))
            frac_time = min(1.0, elapsed / total) if total > 0 else 0.0
            frac = max(frac_rounds, frac_time)
            pct = int((solve_share + improve_share * frac) * 100.0)
            label = f"improve round {round_idx}/{max_rounds}"
            ctx["phase_label"] = label
            self._solve_progress_context = ctx
            self._update_solve_progress_status(pct, label)
            return

        if kind in {"improve_done", "run_done"}:
            self._update_solve_progress_status(99, "finalizing")

    def _focus_penalty_activity_ids(self, term: str, *, limit: int = 80) -> List[int]:
        if self.inst is None or not self.current_schedule:
            return []
        return focus_penalty_activity_ids(
            self.inst,
            self.current_schedule,
            term,
            limit=int(limit),
        )

    def on_focused_cp_sat_polish(self) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule to polish")
            return
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Solver already running.")
            return
        term = self._selected_improve_focus_term()
        if not term:
            QMessageBox.information(
                self,
                "Focused CP-SAT polish",
                "Choose a Focus term first, then run focused CP-SAT polish.",
            )
            self.set_status("Focused CP-SAT polish needs a focus term")
            return
        affected = self._focus_penalty_activity_ids(term, limit=100)
        if not affected:
            self.set_status(f"No activities found for {self._focus_label(term)}")
            return
        prior_locks = {
            int(a_id): dict(lock)
            for a_id, lock in self.locked_activities.items()
            if isinstance(lock, dict)
        }
        self.locked_activities = build_freeze_locks(
            self.current_schedule,
            unlocked_activity_ids=set(int(a_id) for a_id in affected),
        )
        self._sync_locks_to_instance()
        self._restore_locks_after_solve = prior_locks
        profile_before = self.objective_profile_combo.currentData()
        objective_before = self.objective_cb.isChecked()
        room_before = self.room_mode_combo.currentData()
        try:
            profile_idx = self.objective_profile_combo.findData("balanced")
            if profile_idx >= 0:
                self.objective_profile_combo.setCurrentIndex(profile_idx)
            room_idx = self.room_mode_combo.findData("greedy")
            if room_idx >= 0:
                self.room_mode_combo.setCurrentIndex(room_idx)
            self.objective_cb.setChecked(True)
            self.set_status(
                f"Focused CP-SAT polish: {self._focus_label(term)} "
                f"({len(affected)} activities, locks={len(self.locked_activities)})"
            )
            self._append_audit_log(
                "focused_cp_sat_polish_started",
                {
                    "term": str(term),
                    "affected_activities": int(len(affected)),
                    "frozen_activities": int(len(self.locked_activities)),
                },
            )
            self._start_solver_process(keep_locks=True)
        finally:
            profile_restore = self.objective_profile_combo.findData(profile_before)
            if profile_restore >= 0:
                self.objective_profile_combo.setCurrentIndex(profile_restore)
            room_restore = self.room_mode_combo.findData(room_before)
            if room_restore >= 0:
                self.room_mode_combo.setCurrentIndex(room_restore)
            self.objective_cb.setChecked(bool(objective_before))

    def on_show_score_breakdown(self) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule to score")
            return
        try:
            breakdown = compute_penalty_breakdown(self.inst, self.current_schedule)
            drivers = rank_penalty_drivers(self.inst, self.current_schedule, limit=12)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.warning(self, "Score breakdown", str(exc))
            return
        total = int(breakdown.get("total", 0))
        lines = [f"Global soft penalty: {total}", "", "Top penalty drivers:"]
        for row in drivers:
            lines.append(
                f"- {row['term']}: {int(row['penalty'])} "
                f"({float(row['share']) * 100:.1f}%)"
            )
        lines.append("")
        lines.append("All terms:")
        for key, value in sorted(breakdown.items()):
            if key != "total":
                lines.append(f"- {key}: {int(value)}")
        QMessageBox.information(self, "Score breakdown", "\n".join(lines))
        self.set_status(f"Score breakdown shown: soft penalty {total}")

    def _format_solver_attempts(self, res: Dict[str, Any]) -> list[str]:
        meta = res.get("meta")
        if not isinstance(meta, dict):
            return []
        attempts = meta.get("attempts")
        if not isinstance(attempts, list):
            return []
        lines: list[str] = []
        for i, attempt in enumerate(attempts, start=1):
            if not isinstance(attempt, dict):
                continue
            mode = attempt.get("room_mode", "?")
            objective = "on" if attempt.get("use_objective", False) else "off"
            limit = attempt.get("time_limit_seconds")
            limit_txt = "none" if limit in (None, "") else str(limit)
            raw_status = attempt.get("raw_status", attempt.get("status", "?"))
            elapsed = attempt.get("elapsed_seconds")
            elapsed_txt = ""
            if elapsed not in (None, ""):
                try:
                    elapsed_txt = f", elapsed={float(elapsed):.2f}s"
                except Exception:
                    elapsed_txt = f", elapsed={elapsed}s"
            workers = attempt.get("workers")
            workers_txt = "" if workers in (None, "") else f", workers={workers}"
            objective_txt = ""
            if attempt.get("objective_value") not in (None, ""):
                try:
                    objective_txt += f", obj={float(attempt.get('objective_value')):.2f}"
                except Exception:
                    objective_txt += f", obj={attempt.get('objective_value')}"
            if attempt.get("best_objective_bound") not in (None, ""):
                try:
                    objective_txt += f", bound={float(attempt.get('best_objective_bound')):.2f}"
                except Exception:
                    objective_txt += f", bound={attempt.get('best_objective_bound')}"
            if attempt.get("relative_gap") not in (None, ""):
                try:
                    objective_txt += f", gap={float(attempt.get('relative_gap')) * 100.0:.2f}%"
                except Exception:
                    objective_txt += f", gap={attempt.get('relative_gap')}"
            lines.append(
                f"Attempt {i}: mode={mode}, objective={objective}, "
                f"limit={limit_txt}s, raw_status={raw_status}{elapsed_txt}{workers_txt}{objective_txt}"
            )
        return lines

    def _cp_bound_summary_from_meta(self, meta: Dict[str, Any] | None = None) -> str:
        meta = self._last_solver_result_meta if meta is None else meta
        if not isinstance(meta, dict):
            return "CP bound: unavailable"
        attempts = meta.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            return "CP bound: unavailable"
        objective_attempts = [
            attempt
            for attempt in attempts
            if isinstance(attempt, dict) and bool(attempt.get("use_objective", False))
        ]
        if not objective_attempts:
            profile = meta.get("objective_profile")
            if isinstance(profile, dict):
                profile = profile.get("id") or profile.get("label")
            profile_txt = f" ({profile})" if profile else ""
            return (
                f"CP gap: unavailable{profile_txt}; ran without CP objective, "
                "so no lower bound was computed"
            )
        attempt = objective_attempts[-1]
        obj = attempt.get("objective_value")
        bound = attempt.get("best_objective_bound")
        gap = attempt.get("relative_gap")
        if obj in (None, "") and bound in (None, ""):
            return "CP bound: unavailable; objective attempt found no bounded solution"
        parts = ["CP bound/gap"]
        if obj not in (None, ""):
            try:
                parts.append(f"obj={float(obj):.2f}")
            except Exception:
                parts.append(f"obj={obj}")
        if bound not in (None, ""):
            try:
                parts.append(f"best>={float(bound):.2f}")
            except Exception:
                parts.append(f"best>={bound}")
        if gap not in (None, ""):
            try:
                parts.append(f"gap={float(gap) * 100.0:.2f}%")
            except Exception:
                parts.append(f"gap={gap}")
        return " ".join(parts)

    def _build_no_feasible_message(self, res: Dict[str, Any], status: int) -> str:
        if res.get("error"):
            msg = str(res.get("error"))
            if res.get("reason"):
                msg += f"\nReason: {res.get('reason')}"
            return msg

        lines: list[str] = [
            f"No feasible schedule found (status {status}).",
            "",
            "Solver settings:",
            f"- Room mode: {self._selected_room_mode_label()}",
            f"- Profile: {self.objective_profile_combo.currentText()}",
            f"- Objective: {'on' if self.objective_cb.isChecked() else 'off'}",
            f"- Time limit: {self.time_limit_spin.value()}s",
            f"- Workers: {self.workers_preset_combo.currentText()}",
        ]
        attempts = self._format_solver_attempts(res)
        if attempts:
            lines.extend(["", "Attempt details:"])
            lines.extend(f"- {line}" for line in attempts[:6])

        if self.inst is not None:
            reasons = explain_infeasibility(self.inst)
            if reasons:
                lines.extend(["", "Likely causes:"])
                lines.extend(f"- {r}" for r in reasons[:8])
            diagnosis = build_unsat_rule_diagnosis(self.inst)
            if diagnosis:
                lines.extend(["", "Rule diagnosis:"])
                lines.extend(
                    f"- {row['rule_id']}: {row['summary']}"
                    for row in diagnosis[:5]
                )
            else:
                lines.extend(
                    [
                        "",
                        "No specific structural conflict was detected.",
                        "Try increasing Limit, switching Room mode to Fast (Greedy), or disabling Use CP objective.",
                    ]
                )
        return "\n".join(lines)

    def _solver_debug_enabled(self) -> bool:
        if hasattr(self, "debug_diagnostics_cb"):
            try:
                return bool(self.debug_diagnostics_cb.isChecked())
            except Exception:
                pass
        return str(os.getenv("PLANORA_SOLVER_DEBUG", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _activity_room_coverage_debug(self, limit: int = 12) -> list[str]:
        if self.inst is None:
            return ["No instance loaded."]
        inst = self.inst
        missing: list[str] = []
        by_kind: Dict[str, int] = {}
        by_kind_missing: Dict[str, int] = {}
        for act in inst.activities.values():
            kind = str(act.kind)
            by_kind[kind] = int(by_kind.get(kind, 0)) + 1
            need = sum(int(inst.groups[g_id].size) for g_id in act.group_ids if g_id in inst.groups)
            eligible = []
            for room in inst.rooms.values():
                if int(room.capacity) < int(need):
                    continue
                if kind == "LEC" and room.room_type == "LECTURE":
                    eligible.append(room.id)
                elif kind == "TUT" and room.room_type in {"TUTORIAL", "LECTURE"}:
                    eligible.append(room.id)
                elif kind == "LAB":
                    tag = str(getattr(act, "requires_specialization", "") or "").strip()
                    if tag:
                        if room.room_type == "SPECIALIZED_LAB" and tag in set(room.specialization_tags or []):
                            eligible.append(room.id)
                    elif room.room_type in {"COMPUTER_LAB", "SPECIALIZED_LAB"}:
                        eligible.append(room.id)
            if not eligible:
                by_kind_missing[kind] = int(by_kind_missing.get(kind, 0)) + 1
                if len(missing) < int(limit):
                    missing.append(
                        f"A{act.id} {kind} C{act.course_id} W{act.week} "
                        f"groups={act.group_ids} need_cap={need} tag={getattr(act, 'requires_specialization', None) or '-'}"
                    )
        lines = [
            "Room eligibility coverage:",
            f"- Activities by kind: {by_kind}",
            f"- Missing eligible rooms by kind: {by_kind_missing or {}}",
        ]
        if missing:
            lines.append("- Missing samples:")
            lines.extend(f"  {row}" for row in missing)
        return lines

    def _instance_pressure_debug(self, limit: int = 8) -> list[str]:
        if self.inst is None:
            return ["No instance loaded."]
        inst = self.inst
        lines: list[str] = [
            "Instance scale:",
            f"- Programs: {len(inst.programs)}",
            f"- Groups: {len(inst.groups)}",
            f"- Courses: {len(inst.courses)}",
            f"- Staff: {len(inst.staff)} "
            f"(profs={sum(1 for s in inst.staff.values() if s.is_prof)}, "
            f"TAs={sum(1 for s in inst.staff.values() if not s.is_prof)})",
            f"- Rooms: {len(inst.rooms)}",
            f"- Activities: {len(inst.activities)}",
            f"- Calendar: {len(inst.weeks)} weeks x {len(inst.days)} days x {inst.slots_per_day} slots/day",
            f"- Locks: {len(getattr(inst, 'locked_activities', {}) or {})}",
        ]

        room_types: Dict[str, int] = {}
        room_max_caps: Dict[str, int] = {}
        for room in inst.rooms.values():
            r_type = str(room.room_type)
            room_types[r_type] = int(room_types.get(r_type, 0)) + 1
            room_max_caps[r_type] = max(int(room_max_caps.get(r_type, 0)), int(room.capacity))
        lines.extend(
            [
                "Room pool:",
                f"- Counts by type: {room_types}",
                f"- Max capacity by type: {room_max_caps}",
            ]
        )

        group_week_loads: list[tuple[int, int, int, str]] = []
        capacity = len(inst.days) * int(inst.slots_per_day)
        for g_id, group in inst.groups.items():
            for week in inst.weeks:
                load = sum(
                    int(act.duration)
                    for act in inst.activities.values()
                    if int(act.week) == int(week) and int(g_id) in {int(x) for x in act.group_ids}
                )
                group_week_loads.append((int(load), int(g_id), int(week), str(group.name)))
        group_week_loads.sort(reverse=True)
        lines.append("Highest group-week loads:")
        for load, g_id, week, name in group_week_loads[: int(limit)]:
            lines.append(f"- G{g_id} {name} week {week}: {load}/{capacity} slots")

        staff_week_loads: Dict[tuple[int, int], int] = {}
        for act in inst.activities.values():
            staff_id = int(act.prof_id if act.kind == "LEC" else act.ta_id)
            key = (staff_id, int(act.week))
            staff_week_loads[key] = int(staff_week_loads.get(key, 0)) + int(act.duration)
        staff_rows = [
            (load, staff_id, week, str(inst.staff.get(staff_id).name if staff_id in inst.staff else staff_id))
            for (staff_id, week), load in staff_week_loads.items()
        ]
        staff_rows.sort(reverse=True)
        lines.append("Highest staff-week loads:")
        for load, staff_id, week, name in staff_rows[: int(limit)]:
            staff = inst.staff.get(staff_id)
            cap = getattr(staff, "max_slots_per_week", None) if staff is not None else None
            cap_txt = "uncapped" if cap is None else str(cap)
            lines.append(f"- S{staff_id} {name} week {week}: {load} slots, cap={cap_txt}")

        return lines

    def _build_solver_debug_report(self, res: Dict[str, Any], status: int) -> str:
        lines: list[str] = [
            self._build_no_feasible_message(res, int(status)),
            "",
            "===== DEBUG DIAGNOSTICS =====",
            "Status legend:",
            "- UI status -1 = no feasible schedule / CP-SAT UNKNOWN",
            "- UI status -2 = greedy rooming/extraction failed",
            "- UI status -3 = strict hard-conflict gate rejected the returned schedule",
            "- CP-SAT raw status: 0 UNKNOWN, 1 MODEL_INVALID, 2 FEASIBLE, 3 INFEASIBLE, 4 OPTIMAL",
            "",
        ]
        lines.extend(self._instance_pressure_debug())
        lines.append("")
        lines.extend(self._activity_room_coverage_debug())

        if self.inst is not None:
            try:
                certificate = build_feasibility_certificate(self.inst)
                scale = dict(certificate.get("scale", {}) or {})
                recommendation = dict(certificate.get("recommendation", {}) or {})
                decomposition = dict(certificate.get("decomposition", {}) or {})
                lines.extend(
                    [
                        "",
                        "Performance certificate:",
                        f"- Estimated start literals: {scale.get('estimated_start_literals', 0)}",
                        f"- Estimated CP room candidates: {scale.get('estimated_cp_room_candidates', 0)}",
                        f"- Estimated conflict edges: {scale.get('estimated_conflict_edges', 0)}",
                        f"- Recommended profile: {recommendation.get('profile', '?')} "
                        f"(room_mode={recommendation.get('room_mode', '?')}, "
                        f"objective_profile={recommendation.get('objective_profile', '?')})",
                        f"- Reason: {recommendation.get('reason', '')}",
                    ]
                )
                smallest = list(scale.get("smallest_domains", []) or [])[:6]
                if smallest:
                    lines.append("- Smallest activity domains:")
                    lines.extend(
                        f"  A{row.get('activity_id')} {row.get('kind')} W{row.get('week')}: "
                        f"starts={row.get('start_domain')}, rooms={row.get('room_domain')}"
                        for row in smallest
                    )
                week_blocks = list(decomposition.get("week_blocks", []) or [])[:6]
                if week_blocks:
                    lines.append("- Week decomposition samples:")
                    lines.extend(
                        f"  W{row.get('week')}: activities={row.get('activities')}, "
                        f"staff={row.get('staff')}, groups={row.get('groups')}"
                        for row in week_blocks
                    )
            except Exception as exc:
                lines.extend(["", f"Performance certificate unavailable: {exc}"])

            reasons = explain_infeasibility(self.inst, max_per_category=20)
            lines.extend(["", "Expanded structural checks:"])
            if reasons:
                lines.extend(f"- {row}" for row in reasons[:40])
            else:
                lines.append("- No structural issue found by heuristic checks.")

            diagnosis = build_unsat_rule_diagnosis(self.inst)
            lines.extend(["", "Expanded rule diagnosis:"])
            if diagnosis:
                for row in diagnosis[:20]:
                    lines.append(
                        f"- {row.get('rule_id', '?')}: {row.get('summary', '')}"
                    )
            else:
                lines.append("- No rule-level diagnosis rows returned.")

        meta = res.get("meta") if isinstance(res, dict) else {}
        lines.extend(["", "Raw result metadata:", self._format_json_debug(meta)])

        output = str(getattr(self, "_last_solver_output_log", "") or "")
        if output:
            tail = output[-16000:]
            lines.extend(["", "Solver output tail:", tail])
        else:
            lines.extend(["", "Solver output tail:", "(empty)"])

        return "\n".join(lines)

    def _show_solver_report_dialog(self, title: str, text: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(str(title))
        dlg.resize(980, 720)
        layout = QVBoxLayout(dlg)
        editor = QPlainTextEdit(dlg)
        editor.setReadOnly(True)
        editor.setPlainText(str(text))
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(editor)
        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("Close", dlg)
        close_btn.clicked.connect(dlg.accept)
        row.addWidget(close_btn)
        layout.addLayout(row)
        dlg.exec()

    def _require_approval(
        self,
        *,
        action: str,
        details: Dict[str, Any] | None = None,
    ) -> Dict[str, Any] | None:
        dlg = ApprovalDialog(self, action=str(action), actor=str(self._operator_name))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        actor, reason = dlg.values()
        record = build_approval_record(
            action=str(action),
            actor=str(actor or self._operator_name),
            reason=str(reason),
            details=dict(details or {}),
        )
        self._operator_name = str(record.actor)
        self._append_audit_log("override_approved", approval_to_dict(record))
        self._save_persistent_history()
        return approval_to_dict(record)

    def _current_solve_options(self) -> SolveOptions:
        time_limit_seconds = float(self.time_limit_spin.value())
        objective_on = bool(self.objective_cb.isChecked())
        return SolveOptions(
            room_mode=self._selected_room_mode(),
            use_objective=bool(objective_on),
            retry_without_objective=True,
            objective_profile=str(self.objective_profile_combo.currentData() or "balanced"),
            time_limit_seconds=float(time_limit_seconds),
            strict_limit_seconds=min(float(time_limit_seconds), 300.0),
            workers=int(self._selected_worker_count()),
            random_seed=int(self.random_seed_spin.value()),
            phased_solve=bool(objective_on),
            feasibility_seconds=None,
            improve_total_seconds=0.0,
            enforce_hard_conflict_free=True,
        )

    # ----- actions -----

    def on_portfolio_solve_report(self) -> None:
        if self.inst is None:
            self.set_status("Generate or load an instance first")
            return
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Wait for solving to finish first.")
            return
        try:
            self._apply_constraint_settings(self.inst)
            self.set_busy(True)
            self.set_status("Running portfolio solve comparison...")
            QApplication.processEvents()
            portfolio = self.backend_client.solve_portfolio(
                self.inst, self._current_solve_options()
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Portfolio error", str(exc))
            self.set_status("Portfolio solve error")
            return
        finally:
            self.set_busy(False)

        lines: List[str] = ["Portfolio candidates:"]
        for idx, candidate in enumerate(portfolio.candidates, start=1):
            result = candidate.result
            feasibility = "feasible" if result.is_feasible else f"status {result.status}"
            penalty = (
                str(int(candidate.soft_penalty))
                if candidate.soft_penalty is not None
                else "n/a"
            )
            lines.append(
                f"{idx}. {candidate.name}: {feasibility}, penalty={penalty}, attempts={len(result.attempts)}"
            )
            if candidate.rank_explanation:
                lines.append(f"   {candidate.rank_explanation}")

        best = portfolio.best
        if best is None or not best.result.schedule:
            QMessageBox.information(
                self,
                "Portfolio solve report",
                "\n".join(lines),
            )
            self.set_status("Portfolio solve completed with no feasible candidate")
            return

        choice = QMessageBox.question(
            self,
            "Portfolio solve report",
            "\n".join(lines)
            + "\n\nApply the best candidate to the workspace?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        self.set_status(
            f"Portfolio best: {best.name} "
            f"(penalty {int(best.soft_penalty or 0)})"
        )
        if choice != QMessageBox.StandardButton.Yes:
            return

        self.base_schedule = {
            int(a_id): dict(info) for a_id, info in best.result.schedule.items()
        }
        self.current_schedule = {
            int(a_id): dict(info) for a_id, info in best.result.schedule.items()
        }
        self._set_manual_highlight_base(self.current_schedule)
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self._append_audit_log(
            "portfolio_solve_applied",
            {
                "profile": str(best.name),
                "penalty": int(best.soft_penalty or 0),
            },
        )

    def _cleanup_solver_temp_files(self) -> None:
        for path in (self.tmp_inst_path, self.tmp_res_path):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self.tmp_inst_path = None
        self.tmp_res_path = None

    @staticmethod
    def _is_access_violation_exit_code(exit_code: int) -> bool:
        return int(exit_code) in {-1073741819, 3221225477}

    @staticmethod
    def _is_solver_process_crash_error(error: Any) -> bool:
        try:
            if int(error) == int(QProcess.ProcessError.Crashed):
                return True
        except Exception:
            pass
        name = str(getattr(error, "name", "") or "").lower()
        return "crash" in name

    def _retry_solver_once_in_safe_mode(self, *, reason: str, detail: Dict[str, Any]) -> bool:
        if not getattr(sys, "frozen", False):
            return False
        if self._solver_safe_retry_used:
            return False
        self._solver_safe_retry_used = True
        payload: Dict[str, Any] = {"reason": str(reason)}
        payload.update({str(k): v for k, v in detail.items()})
        self._append_audit_log("solve_crash_safe_retry", payload)
        self._cleanup_solver_temp_files()
        self.set_status(
            "Solver worker crashed (native dependency). Retrying once in safe mode..."
        )
        self._start_solver_process(
            keep_locks=bool(self._last_solver_keep_locks),
            retry_safe=True,
        )
        return True

    def _start_solver_process(self, *, keep_locks: bool, retry_safe: bool = False) -> None:
        if self.inst is None:
            self.set_status("Generate instance first")
            return
        if self.proc is not None:
            QMessageBox.warning(self, "Busy", "Solver already running.")
            return
        if not retry_safe:
            self._solver_safe_retry_used = False
        self._last_solver_keep_locks = bool(keep_locks)

        if not keep_locks:
            self.locked_activities = {}

        # Push locks into the instance so the worker can fix them.
        self.inst.locked_activities = dict(self.locked_activities)
        self._apply_constraint_settings(self.inst)

        tmp_dir = tempfile.gettempdir()
        inst_name = f"tt_inst_{uuid.uuid4().hex}.pkl"
        res_name = f"tt_res_{uuid.uuid4().hex}.pkl"
        self.tmp_inst_path = os.path.join(tmp_dir, inst_name)
        self.tmp_res_path = os.path.join(tmp_dir, res_name)

        try:
            with open(self.tmp_inst_path, "wb") as f:
                pickle.dump(self.inst, f)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "File error", f"Cannot write instance: {e}")
            self.tmp_inst_path = None
            self.tmp_res_path = None
            return

        self.proc = QProcess(self)
        if getattr(sys, "frozen", False):
            # In packaged mode, prefer a dedicated worker executable to avoid
            # self-spawn edge-cases with native solver dependencies.
            exe_dir = os.path.dirname(sys.executable)
            worker_exe = os.path.join(exe_dir, "SchedulerEngine.exe")
            if os.path.exists(worker_exe):
                self.proc.setProgram(worker_exe)
                self.proc.setArguments([self.tmp_inst_path, self.tmp_res_path])
            else:
                self.proc.setProgram(sys.executable)
                self.proc.setArguments(
                    ["--engine-cli", self.tmp_inst_path, self.tmp_res_path]
                )
            try:
                self.proc.setWorkingDirectory(exe_dir)
            except Exception:
                pass
        else:
            python_exe = sys.executable
            base_dir = os.path.dirname(os.path.abspath(__file__))
            solver_script = os.path.normpath(
                os.path.join(base_dir, "..", "core", "engine_cli.py")
            )
            self.proc.setProgram(python_exe)
            self.proc.setArguments(
                [solver_script, self.tmp_inst_path, self.tmp_res_path]
            )
        env_map = os.environ.copy()
        time_limit_seconds = float(self.time_limit_spin.value())
        objective_profile = str(
            self.objective_profile_combo.currentData() or "balanced"
        )
        objective_on = self.objective_cb.isChecked()
        room_mode = self._selected_room_mode()
        if objective_profile in {"fast_feasible", "university_fast"}:
            objective_on = False
            if objective_profile == "university_fast":
                room_mode = "greedy"
        elif objective_profile == "university_quality":
            objective_on = True
            room_mode = "greedy"
        elif objective_profile == "verification":
            objective_on = True
            room_mode = "cp_rooms"
        elif objective_profile == "quality_first":
            objective_on = True
        worker_count = int(self._selected_worker_count())
        if retry_safe:
            objective_on = False
            room_mode = "greedy"
            worker_count = 1
            objective_profile = "fast_feasible"
        env_map["TT_ROOM_MODE"] = room_mode
        env_map["TT_TIME_LIMIT"] = str(self.time_limit_spin.value())
        env_map["TT_CP_WORKERS"] = str(int(worker_count))
        env_map["TT_RANDOM_SEED"] = str(int(self.random_seed_spin.value()))
        env_map["TT_USE_OBJECTIVE"] = "1" if objective_on else "0"
        env_map["TT_OBJECTIVE_PROFILE"] = str(objective_profile)
        if self._solver_debug_enabled():
            env_map["TT_CP_LOG"] = "1"
            env_map["PLANORA_SOLVER_DEBUG"] = "1"
        phased_enabled = bool(objective_on)
        feasibility_seconds = float(time_limit_seconds)
        improve_budget_seconds = 0.0
        improve_max_rounds = 0
        if objective_profile == "quality_first":
            feasibility_seconds = min(
                float(time_limit_seconds),
                max(1.0, float(time_limit_seconds) * 0.65),
            )
            improve_budget_seconds = max(
                0.0,
                float(time_limit_seconds) - float(feasibility_seconds),
            )
            env_map["TT_PHASED_SOLVE"] = "1"
            env_map["TT_FEASIBILITY_SECONDS"] = f"{feasibility_seconds:g}"
            env_map["TT_IMPROVE_TOTAL_SECONDS"] = f"{improve_budget_seconds:g}"
            env_map["TT_IMPROVE_SLICE_SECONDS"] = "6"
            env_map["TT_IMPROVE_ITERS_PER_SLICE"] = "1500"
            env_map["TT_IMPROVE_MAX_ROUNDS"] = "16"
            improve_max_rounds = 16
            phased_enabled = True
        elif objective_on:
            # Feasibility-first then iterative improvement within the total solve budget.
            feasibility_seconds, improve_budget_seconds = self._split_phased_budget(time_limit_seconds)
            env_map["TT_PHASED_SOLVE"] = "1"
            env_map["TT_FEASIBILITY_SECONDS"] = f"{feasibility_seconds:g}"
            env_map["TT_IMPROVE_TOTAL_SECONDS"] = f"{improve_budget_seconds:g}"
            env_map["TT_IMPROVE_SLICE_SECONDS"] = "5"
            env_map["TT_IMPROVE_ITERS_PER_SLICE"] = "1200"
            env_map["TT_IMPROVE_MAX_ROUNDS"] = "12"
            improve_max_rounds = 12
        else:
            env_map["TT_PHASED_SOLVE"] = "0"
            env_map["TT_IMPROVE_TOTAL_SECONDS"] = "0"
            phased_enabled = False
        # ensure the worker can import core/utils modules
        env_map["PYTHONPATH"] = os.pathsep.join([os.path.dirname(os.path.dirname(os.path.abspath(__file__))), env_map.get("PYTHONPATH", "")])
        if getattr(sys, "frozen", False):
            bundle_dir = str(getattr(sys, "_MEIPASS", "") or "")
            exe_dir = os.path.dirname(sys.executable)
            path_parts = [p for p in [bundle_dir, exe_dir, env_map.get("PATH", "")] if p]
            env_map["PATH"] = os.pathsep.join(path_parts)
        try:
            from PyQt6.QtCore import QProcessEnvironment

            penv = QProcessEnvironment.systemEnvironment()
            for k, v in env_map.items():
                penv.insert(k, str(v))
            self.proc.setProcessEnvironment(penv)
        except Exception:
            # Fallback for platforms without QProcessEnvironment
            self.proc.setEnvironment([f"{k}={v}" for k, v in env_map.items()])
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.finished.connect(self.on_solver_finished)
        self.proc.errorOccurred.connect(self.on_solver_error)
        self.proc.readyRead.connect(self.on_solver_output_ready)

        expected_attempts = self._expected_solver_attempts(
            phased=bool(phased_enabled),
            room_mode=room_mode,
            objective_on=bool(objective_on),
        )
        self._solve_progress_context = {
            "phased": bool(phased_enabled),
            "room_mode": str(room_mode),
            "objective_on": bool(objective_on),
            "objective_profile": str(objective_profile),
            "expected_attempts": int(expected_attempts),
            "attempt": 1,
            "completed_attempts": 0,
            "attempt_limit_seconds": float(max(1.0, feasibility_seconds if phased_enabled else time_limit_seconds)),
            "feasibility_seconds": float(max(0.0, feasibility_seconds)),
            "improve_total_seconds": float(max(0.0, improve_budget_seconds)),
            "improve_max_rounds": int(max(0, improve_max_rounds)),
            "phase_label": "starting",
        }
        self._solver_output_log = ""
        self._solver_output_partial = ""
        self._last_solver_output_log = ""

        self.set_busy(True)
        lock_count = len(self.locked_activities)
        mode_hint = " [safe retry]" if retry_safe else ""
        self.set_status(
            "Solving in external process..."
            + mode_hint
            + (f" (locks={lock_count})" if lock_count else "")
        )
        self._start_solve_progress()
        self.proc.start()

    def on_solve(self):
        self._restore_locks_after_solve = None
        self._append_audit_log("solve_started", {"keep_locks": False})
        self._start_solver_process(keep_locks=False)

    def on_solver_error(self, error):
        sender_proc = self.sender()
        if (
            sender_proc is not None
            and self.proc is not None
            and sender_proc is not self.proc
        ):
            return
        proc = self.proc
        self.set_busy(False)
        self._stop_solve_progress()
        output = str(self._solver_output_log or "")
        if proc is not None:
            try:
                output += proc.readAll().data().decode("utf-8", errors="ignore")
            except Exception:
                pass
        self.proc = None
        self._last_solver_output_log = str(output)
        self._solver_output_log = ""
        if (
            self._is_solver_process_crash_error(error)
            and self._retry_solver_once_in_safe_mode(
                reason="qprocess_error",
                detail={
                    "error": str(error),
                    "keep_locks": bool(self._last_solver_keep_locks),
                },
            )
        ):
            if proc is not None:
                try:
                    proc.deleteLater()
                except Exception:
                    pass
            return

        msg = output or f"QProcess error: {error}"
        if self._is_solver_process_crash_error(error):
            msg += (
                "\n\nNative worker crash detected.\n"
                "Try: workers=Min, objective off, or reinstall the packaged app."
            )
            try:
                write_crash_report(
                    self._runtime_paths["crash_dir"],
                    error_type="SolverWorkerCrash",
                    message=str(error),
                    traceback_text=output,
                    context={"phase": "qprocess_error"},
                    opt_in=bool(self._runtime_settings.get("crash_reports_opt_in", False)),
                )
            except Exception:
                pass
        QMessageBox.critical(self, "Solver error", msg)
        self._append_audit_log("solve_error", {"error": str(error)})
        self._restore_locks_if_needed()
        if proc is not None:
            try:
                proc.deleteLater()
            except Exception:
                pass
        self._cleanup_solver_temp_files()
        self.set_status("Solve error")

    def on_solver_finished(self, exit_code: int, exit_status):
        sender_proc = self.sender()
        if (
            sender_proc is not None
            and self.proc is not None
            and sender_proc is not self.proc
        ):
            return
        proc = self.proc
        if proc is not None:
            try:
                self.on_solver_output_ready()
            except Exception:
                pass
        self._update_solve_progress_status(99, "finalizing")
        self.set_busy(False)
        self._stop_solve_progress()

        output = str(self._solver_output_log or "")
        if proc is not None:
            try:
                output += proc.readAll().data().decode("utf-8", errors="ignore")
            except Exception:
                pass
        self.proc = None
        self._last_solver_output_log = str(output)
        self._solver_output_log = ""
        if proc is not None:
            try:
                proc.deleteLater()
            except Exception:
                pass

        if exit_code != 0:
            if (
                self._is_access_violation_exit_code(int(exit_code))
                and self._retry_solver_once_in_safe_mode(
                    reason="exit_code",
                    detail={
                        "exit_code": int(exit_code),
                        "keep_locks": bool(self._last_solver_keep_locks),
                    },
                )
            ):
                return
            msg = output or f"Solver exited with code {exit_code}"
            if self._is_access_violation_exit_code(int(exit_code)):
                msg += (
                    "\n\nWindows code 0xC0000005 (access violation): "
                    "a native dependency crashed.\n"
                    "Try: workers=Min, objective off, or reinstall the packaged app."
                )
                try:
                    write_crash_report(
                        self._runtime_paths["crash_dir"],
                        error_type="SolverWorkerExitCode",
                        message=f"Exit code {int(exit_code)}",
                        traceback_text=output,
                        context={"phase": "finished"},
                        opt_in=bool(self._runtime_settings.get("crash_reports_opt_in", False)),
                    )
                except Exception:
                    pass
            QMessageBox.critical(
                self,
                "Solver crashed",
                msg,
            )
            self._append_audit_log("solve_crash", {"exit_code": int(exit_code)})
            self._restore_locks_if_needed()
            self._cleanup_solver_temp_files()
            self.set_status(f"Solver failed (code {exit_code})")
            return

        if not self.tmp_res_path or not os.path.exists(self.tmp_res_path):
            QMessageBox.critical(self, "Result error", "Result file not found.")
            self._append_audit_log("solve_result_missing", {})
            self._restore_locks_if_needed()
            self._cleanup_solver_temp_files()
            self.set_status("Solve error")
            return

        try:
            with open(self.tmp_res_path, "rb") as f:
                res = pickle.load(f)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Result error", f"Cannot read result: {e}")
            self._append_audit_log("solve_result_read_error", {"error": str(e)})
            self._restore_locks_if_needed()
            self._cleanup_solver_temp_files()
            self.set_status("Solve error")
            return
        finally:
            self._cleanup_solver_temp_files()

        meta = res.get("meta")
        self._last_solver_result_meta = dict(meta) if isinstance(meta, dict) else {}
        status = res.get("status", -1)
        if status not in (0, 4):  # 0=FEASIBLE, 4=OPTIMAL
            self.base_schedule = {}
            self._set_manual_highlight_base({})
            self.current_schedule = {}
            self.held_activity_id = None
            self._bump_schedule_revision()
            self._reset_history()
            self.clear_table()
            self.set_status(f"No feasible schedule (status {status})")
            if self._solver_debug_enabled():
                msg = self._build_solver_debug_report(res, int(status))
                self._show_solver_report_dialog(
                    "No feasible schedule - Debug diagnostics",
                    msg,
                )
            else:
                msg = self._build_no_feasible_message(res, int(status))
                QMessageBox.information(self, "No feasible schedule", msg)
            self._append_audit_log(
                "solve_no_feasible",
                {"status": int(status), "attempts": self._format_solver_attempts(res)},
            )
            self._restore_locks_if_needed()
            return

        self.base_schedule = res.get("schedule", {})
        if not isinstance(self.base_schedule, dict):
            self.base_schedule = {}
        self.base_schedule = {
            int(a_id): dict(info)
            for a_id, info in self.base_schedule.items()
            if isinstance(info, dict)
        }
        base_hard_errors = self._validate_schedule_hard_errors(
            self.base_schedule, require_all=True
        )
        if base_hard_errors:
            self.base_schedule = {}
            self._set_manual_highlight_base({})
            self.current_schedule = {}
            self.held_activity_id = None
            self._bump_schedule_revision()
            self._reset_history()
            self.clear_table()
            self.set_status(
                f"Solve rejected: hard conflicts detected ({len(base_hard_errors)})"
            )
            sample = "\n".join(f"- {line}" for line in base_hard_errors[:12])
            message = (
                "The solver returned a schedule with hard conflicts and it was rejected.\n\n"
                f"Conflicts: {len(base_hard_errors)}\n\n"
                f"{sample}"
            )
            if self._solver_debug_enabled():
                debug_payload = {
                    "status": -3,
                    "schedule": {},
                    "error": "The solver returned a schedule with hard conflicts and it was rejected.",
                    "meta": {
                        "hard_conflicts": {
                            "count": len(base_hard_errors),
                            "sample": base_hard_errors[:25],
                            "stage": "ui_post_extract",
                        }
                    },
                }
                self._show_solver_report_dialog(
                    "Invalid solve result - Debug diagnostics",
                    message + "\n\n" + self._build_solver_debug_report(debug_payload, -3),
                )
            else:
                QMessageBox.critical(
                    self,
                    "Invalid solve result",
                    message,
                )
            self._append_audit_log(
                "solve_rejected_hard_conflicts", {"count": len(base_hard_errors)}
            )
            self._restore_locks_if_needed()
            return

        self.current_schedule = {
            a_id: info.copy() for a_id, info in self.base_schedule.items()
        }
        self._set_manual_highlight_base(self.current_schedule)
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        attempts = self._format_solver_attempts(res)
        final_attempt = attempts[-1] if attempts else ""

        try:
            if self.inst is not None and self.current_schedule:
                ls_seconds = float(self.ls_time_spin.value() or 0)
                if ls_seconds <= 0:
                    status_msg = f"Solved (status {status})"
                    if final_attempt:
                        status_msg += f" | {final_attempt}"
                    self.set_status(status_msg)
                    self.populate_weeks()
                    self.update_entities()
                    self.update_table()
                    self.update_quality_summary()
                    self._append_audit_log(
                        "solve_finished",
                        {"status": int(status), "activities": int(len(self.current_schedule))},
                    )
                    self._restore_locks_if_needed()
                    self._save_persistent_history()
                    return
                focus_term = self._selected_improve_focus_term()
                improve_inst = self._build_focused_improve_instance(focus_term)
                ls = LocalSearchImprover(improve_inst)
                before = ls.compute_soft_penalty(self.current_schedule)
                improved = ls.improve(
                    self.current_schedule,
                    iterations=int(self.improve_runs_spin.value()),
                    max_seconds=ls_seconds,
                )
                improved_hard_errors = self._validate_schedule_hard_errors(
                    improved, require_all=True
                )
                if improved_hard_errors:
                    self.set_status(
                        f"Solved (status {status}); post-solve improvement rejected "
                        f"({len(improved_hard_errors)} hard conflicts)."
                    )
                else:
                    after = ls.compute_soft_penalty(improved)
                    self.current_schedule = {
                        a_id: info.copy() for a_id, info in improved.items()
                    }
                    self._set_manual_highlight_base(self.current_schedule)
                    self._bump_schedule_revision()
                    metric = (
                        f"{self._focus_label(focus_term)} focus penalty"
                        if focus_term
                        else "soft penalty"
                    )
                    status_msg = (
                        f"Solved (status {status}), {metric} {before} -> {after}"
                    )
                    if final_attempt:
                        status_msg += f" | {final_attempt}"
                    self.set_status(status_msg)
        except Exception:
            traceback.print_exc()
            status_msg = f"Solved (status {status}), local search skipped"
            if final_attempt:
                status_msg += f" | {final_attempt}"
            self.set_status(status_msg)

        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self._append_audit_log(
            "solve_finished",
            {"status": int(status), "activities": int(len(self.current_schedule))},
        )
        self._restore_locks_if_needed()
        self._save_persistent_history()

    def on_improve(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to improve")
            return

        start_hard_errors = self._collect_conflict_errors()
        if start_hard_errors:
            sample = "\n".join(f"- {line}" for line in start_hard_errors[:8])
            QMessageBox.warning(
                self,
                "Improve blocked",
                "Cannot run improvement while hard constraints are violated.\n\n"
                f"Conflicts: {len(start_hard_errors)}\n{sample}\n\n"
                "Use Conflicts -> Solve Conflicts first.",
            )
            self.set_status(
                f"Improve blocked: {len(start_hard_errors)} hard conflicts present"
            )
            return

        self._improve_total_iters = int(self.improve_runs_spin.value())
        self._improve_original_schedule = {
            a_id: info.copy() for a_id, info in self.current_schedule.items()
        }
        self._improve_focus_term = self._selected_improve_focus_term()
        improve_inst = self._build_focused_improve_instance(self._improve_focus_term)
        try:
            self._improve_base_penalty = LocalSearchImprover(improve_inst).compute_soft_penalty(
                self._improve_original_schedule
            )
        except Exception:
            self._improve_base_penalty = None
        self._live_improve_mode = True
        self._improve_running = True
        self._improve_stop_requested = False
        self.stop_improve_button.setEnabled(True)
        self.set_busy(True)
        focus_note = (
            f" focused on {self._focus_label(self._improve_focus_term)}"
            if self._improve_focus_term
            else ""
        )
        self.set_status(f"Improving{focus_note}... 0% (iter 0/{self._improve_total_iters})")

        self._improve_thread = QThread(self)
        self._improve_worker = ImproveWorker(
            improve_inst,
            self._improve_original_schedule,
            iterations=int(self._improve_total_iters),
            max_seconds=(float(self.ls_time_spin.value()) or None),
        )
        self._improve_worker.moveToThread(self._improve_thread)
        self._improve_thread.started.connect(self._improve_worker.run)
        self._improve_worker.progress.connect(self._on_improve_worker_progress)
        self._improve_worker.finished.connect(self._on_improve_worker_finished)
        self._improve_worker.error.connect(self._on_improve_worker_error)
        self._improve_worker.finished.connect(self._cleanup_improve_worker)
        self._improve_worker.error.connect(self._cleanup_improve_worker)
        self._improve_thread.start()

    def _on_improve_worker_progress(
        self,
        it_done: int,
        best_pen: int,
        cur_pen: int,
        snapshot: object,
    ) -> None:
        if isinstance(snapshot, dict):
            self.current_schedule = {
                int(a_id): dict(info) for a_id, info in snapshot.items()
            }
            self.update_table()
            self.update_quality_summary()
        pct = int(
            min(
                99,
                max(0.0, float(it_done) / max(1.0, float(self._improve_total_iters))) * 100.0,
            )
        )
        base_pen = self._improve_base_penalty
        if base_pen is None:
            self.set_status(
                f"Improving... {pct}% (iter {int(it_done)}/{self._improve_total_iters}, current={int(cur_pen)}, best={int(best_pen)})"
            )
        else:
            self.set_status(
                f"Improving... {pct}% (iter {int(it_done)}/{self._improve_total_iters}, original={int(base_pen)}, current={int(cur_pen)}, best={int(best_pen)})"
            )

    def _on_improve_worker_finished(
        self,
        improved: object,
        start_pen: int,
        final_pen: int,
    ) -> None:
        original_schedule = self._improve_original_schedule or {}
        improved_schedule = (
            {int(a_id): dict(info) for a_id, info in improved.items()}
            if isinstance(improved, dict)
            else {}
        )
        improved_hard_errors = self._validate_schedule_hard_errors(
            improved_schedule, require_all=True
        )
        self.current_schedule = {
            int(a_id): dict(info) for a_id, info in original_schedule.items()
        }
        self._live_improve_mode = False
        if improved_hard_errors:
            self.update_table()
            self.update_quality_summary()
            self.set_status(
                f"Improvement rejected: {len(improved_hard_errors)} hard conflicts detected"
            )
            return
        if improved_schedule != original_schedule:
            self._push_undo_state()
        metric_label = (
            f"{self._focus_label(self._improve_focus_term)} focus penalty"
            if self._improve_focus_term
            else "global penalty"
        )
        self._commit_schedule(
            improved_schedule,
            f"Improved {metric_label} {int(start_pen)} -> {int(final_pen)}"
            + (" [stopped]" if self._improve_stop_requested else ""),
        )
        self._set_manual_highlight_base(self.current_schedule)
        if improved_schedule != original_schedule:
            self._show_improvement_delta_report(
                original_schedule,
                improved_schedule,
                title="Improve before/after report",
            )

    def _on_improve_worker_error(self, message: str) -> None:
        traceback.print_exc()
        QMessageBox.critical(self, "Improve error", str(message))
        if self._improve_original_schedule is not None:
            self.current_schedule = {
                int(a_id): dict(info)
                for a_id, info in self._improve_original_schedule.items()
            }
            self.update_table()
            self.update_quality_summary()
        self.set_status("Improve error")

    def _cleanup_improve_worker(self, *_args: Any) -> None:
        self._live_improve_mode = False
        self._improve_running = False
        self._improve_stop_requested = False
        self._improve_base_penalty = None
        self._improve_focus_term = ""
        self.stop_improve_button.setEnabled(False)
        self.set_busy(False)
        if self._improve_thread is not None:
            self._improve_thread.quit()
            self._improve_thread.wait(1000)
            self._improve_thread.deleteLater()
            self._improve_thread = None
        if self._improve_worker is not None:
            self._improve_worker.deleteLater()
            self._improve_worker = None

    def on_stop_improve(self) -> None:
        if not self._improve_running:
            self.set_status("No active improve run")
            return
        self._improve_stop_requested = True
        if self._improve_worker is not None:
            self._improve_worker.request_stop()
        self.set_status("Stopping improvement at next safe checkpoint...")
