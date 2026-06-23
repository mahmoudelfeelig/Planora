from __future__ import annotations

from ui.window_runtime import *  # noqa: F401,F403


class WindowHistoryMixin:

    def _append_audit_log(self, event: str, details: Dict[str, Any] | None = None) -> None:
        row = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "user": str(self._operator_name or "unknown"),
            "event": str(event),
            "details": details or {},
        }
        details_summary_parts: List[str] = []
        for key, value in sorted((details or {}).items()):
            if isinstance(value, (dict, list, tuple)):
                details_summary_parts.append(f"{key}=...")
            else:
                details_summary_parts.append(f"{key}={value}")
        row["details_summary"] = ", ".join(details_summary_parts[:4])
        self._workspace_change_log.append(dict(row))
        if len(self._workspace_change_log) > 200:
            self._workspace_change_log = self._workspace_change_log[-200:]
        try:
            append_runtime_log(
                self._runtime_paths["runtime_log"],
                event=str(event),
                level="info",
                details=dict(details or {}),
            )
            record_telemetry_event(
                self._runtime_paths["telemetry_log"],
                event=str(event),
                details=dict(details or {}),
                opt_in=bool(self._runtime_settings.get("telemetry_opt_in", False)),
            )
        except Exception:
            pass
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        try:
            with open(self._audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, sort_keys=True) + "\n")
        except Exception:
            pass

    def _state_to_json_ready(self, state: Dict[str, Any]) -> Dict[str, Any]:
        out = {
            "current_schedule": {},
            "locked_activities": {},
            "held_activity_id": state.get("held_activity_id"),
        }
        cur = state.get("current_schedule") or {}
        if isinstance(cur, dict):
            out["current_schedule"] = {
                str(int(a_id)): dict(info)
                for a_id, info in cur.items()
                if isinstance(info, dict)
            }
        locks = state.get("locked_activities") or {}
        if isinstance(locks, dict):
            out["locked_activities"] = {
                str(int(a_id)): dict(lock)
                for a_id, lock in locks.items()
                if isinstance(lock, dict)
        }
        return out

    def _workspace_meta(self) -> Dict[str, Any]:
        return {
            "operator_name": str(self._operator_name or "unknown"),
            "branches": {
                str(name): dict(branch)
                for name, branch in self._branches.items()
                if isinstance(branch, dict)
            },
            "active_branch_name": self._active_branch_name,
            "release_candidates": {
                str(name): dict(candidate)
                for name, candidate in self._release_candidates.items()
                if isinstance(candidate, dict)
            },
            "published_release_id": self._published_release_id,
            "protected_baseline": dict(self._protected_baseline or {}),
            "change_history": [dict(row) for row in self._workspace_change_log[-200:]],
            "import_export_template_store_path": str(self._import_export_template_path),
            "branding_profile": dict(self._branding_profile or {}),
            "runtime_settings": dict(self._runtime_settings or {}),
            "last_import_mapping": dict(self._last_import_mapping or {}),
            "last_group_separator": str(self._last_group_separator or ";"),
        }

    def _effective_branding(self) -> Dict[str, Any]:
        return ensure_branding_profile(self._branding_profile)

    def _apply_branding_profile(self) -> None:
        branding = self._effective_branding()
        self.setWindowTitle(str(branding.get("display_name", APP_DISPLAY_NAME)))
        if hasattr(self, "status_label"):
            self._refresh_status_label()
        if hasattr(self, "quality_label") and not self.quality_label.text().strip():
            self.quality_label.setText(
                f"{branding.get('display_name', APP_DISPLAY_NAME)} ready."
            )

    @staticmethod
    def _state_from_json_ready(state: Dict[str, Any]) -> Dict[str, Any]:
        cur = state.get("current_schedule") or {}
        locks = state.get("locked_activities") or {}
        return {
            "current_schedule": {
                int(a_id): dict(info)
                for a_id, info in cur.items()
                if isinstance(info, dict)
            },
            "locked_activities": {
                int(a_id): dict(lock)
                for a_id, lock in locks.items()
                if isinstance(lock, dict)
            },
            "held_activity_id": state.get("held_activity_id"),
        }

    def _save_persistent_history(self) -> None:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        if self.inst is None:
            return
        try:
            payload = {
                "saved_at_utc": datetime.now(timezone.utc).isoformat(),
                "instance": instance_to_json(self.inst),
                "base_schedule": {
                    str(int(a_id)): dict(info)
                    for a_id, info in self.base_schedule.items()
                    if isinstance(info, dict)
                },
                "state": self._state_to_json_ready(self._snapshot_state()),
                "undo": [
                    self._state_to_json_ready(s)
                    for s in self._undo_stack[-60:]
                    if isinstance(s, dict)
                ],
                "redo": [
                    self._state_to_json_ready(s)
                    for s in self._redo_stack[-60:]
                    if isinstance(s, dict)
                ],
                "workspace_meta": self._workspace_meta(),
            }
            with open(self._history_store_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
        except Exception:
            pass

    def _load_persistent_history(self) -> None:
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        if not os.path.exists(self._history_store_path):
            return
        try:
            with open(self._history_store_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return
            inst_raw = payload.get("instance")
            if not isinstance(inst_raw, dict):
                return
            inst = instance_from_json(inst_raw)
            self.inst = inst
            base_raw = payload.get("base_schedule", {})
            if isinstance(base_raw, dict):
                self.base_schedule = {
                    int(a_id): dict(info)
                    for a_id, info in base_raw.items()
                    if isinstance(info, dict)
                }
            state_raw = payload.get("state", {})
            state = self._state_from_json_ready(state_raw if isinstance(state_raw, dict) else {})
            self.current_schedule = {
                int(a_id): dict(info)
                for a_id, info in (state.get("current_schedule") or {}).items()
            }
            self.locked_activities = {
                int(a_id): dict(lock)
                for a_id, lock in (state.get("locked_activities") or {}).items()
            }
            held = state.get("held_activity_id")
            self.held_activity_id = int(held) if held is not None else None
            self._bump_schedule_revision()
            self._undo_stack = [
                self._state_from_json_ready(s)
                for s in (payload.get("undo") or [])
                if isinstance(s, dict)
            ]
            self._redo_stack = [
                self._state_from_json_ready(s)
                for s in (payload.get("redo") or [])
                if isinstance(s, dict)
            ]
            workspace_meta = payload.get("workspace_meta", {})
            if isinstance(workspace_meta, dict):
                self._operator_name = str(
                    workspace_meta.get("operator_name", self._operator_name) or self._operator_name
                )
                self._branches = {
                    str(name): dict(branch)
                    for name, branch in dict(workspace_meta.get("branches", {}) or {}).items()
                    if isinstance(branch, dict)
                }
                active_branch = workspace_meta.get("active_branch_name")
                self._active_branch_name = str(active_branch) if active_branch else None
                self._release_candidates = {
                    str(name): dict(candidate)
                    for name, candidate in dict(workspace_meta.get("release_candidates", {}) or {}).items()
                    if isinstance(candidate, dict)
                }
                published = workspace_meta.get("published_release_id")
                self._published_release_id = str(published) if published else None
                self._protected_baseline = dict(
                    workspace_meta.get("protected_baseline", self._protected_baseline) or {}
                )
                self._workspace_change_log = [
                    dict(row)
                    for row in list(workspace_meta.get("change_history", []) or [])
                    if isinstance(row, dict)
                ][-200:]
                self._import_export_template_path = str(
                    workspace_meta.get(
                        "import_export_template_store_path",
                        self._import_export_template_path,
                    )
                    or self._import_export_template_path
                )
                self._branding_profile = ensure_branding_profile(
                    dict(workspace_meta.get("branding_profile", self._branding_profile) or {})
                )
                self._runtime_settings = save_runtime_settings(
                    self._runtime_paths["settings"],
                    dict(workspace_meta.get("runtime_settings", self._runtime_settings) or {}),
                )
                self._last_import_mapping = {
                    str(k): str(v)
                    for k, v in dict(workspace_meta.get("last_import_mapping", {}) or {}).items()
                }
                self._last_group_separator = str(
                    workspace_meta.get("last_group_separator", self._last_group_separator) or self._last_group_separator
                )
            self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
            self._sync_instance_staff_from_schedule(self.current_schedule)
            self._sync_locks_to_instance()
            self._load_constraint_controls_from_instance(self.inst)
            self.populate_weeks()
            self.update_entities()
            self.update_table()
            self.update_quality_summary()
            self._refresh_history_buttons()
            self._apply_branding_profile()
            self.set_status("Restored previous workspace history.")
        except Exception:
            # Corrupted history should never break app startup.
            pass

    def _history_state_brief(self, state: Dict[str, Any]) -> str:
        cur = state.get("current_schedule") or {}
        locks = state.get("locked_activities") or {}
        held = state.get("held_activity_id")
        held_txt = f"A{int(held)}" if held is not None else "none"
        return (
            f"activities={len(cur) if isinstance(cur, dict) else 0}, "
            f"locks={len(locks) if isinstance(locks, dict) else 0}, held={held_txt}"
        )

    def _ensure_snapshot_store_dir(self) -> str:
        path = str(self._snapshot_store_dir)
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            fallback = os.path.join(
                tempfile.gettempdir(), "scheduler_history_snapshots"
            )
            os.makedirs(fallback, exist_ok=True)
            self._snapshot_store_dir = str(fallback)
            return str(fallback)

    def _refresh_history_view(self) -> None:
        if not hasattr(self, "history_list"):
            return
        self.history_list.clear()
        if self.inst is None:
            self.history_list.addItem("No active instance.")
            return

        undo_count = len(self._undo_stack)
        for idx, state in enumerate(self._undo_stack):
            steps = max(1, int(undo_count - idx))
            line = f"o  undo {steps:02d}  {self._history_state_brief(state)}"
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, ("undo", int(steps)))
            self.history_list.addItem(item)

        head_item = QListWidgetItem(f"*  HEAD      {self._history_state_brief(self._snapshot_state())}")
        head_item.setData(Qt.ItemDataRole.UserRole, ("head", 0))
        self.history_list.addItem(head_item)

        for idx, state in enumerate(reversed(self._redo_stack), start=1):
            line = f"o  redo {idx:02d}  {self._history_state_brief(state)}"
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, ("redo", int(idx)))
            self.history_list.addItem(item)

        branch_rows = list_branch_rows(self._branches)
        if branch_rows:
            self.history_list.addItem(QListWidgetItem("---- named branches ----"))
            for row in branch_rows:
                item = QListWidgetItem(
                    f"  {row['name']} | {row['author']} | {row['description']}"
                )
                item.setData(Qt.ItemDataRole.UserRole, ("branch", str(row["name"])))
                self.history_list.addItem(item)

        if self._release_candidates:
            self.history_list.addItem(QListWidgetItem("---- release candidates ----"))
            for name, candidate in sorted(self._release_candidates.items()):
                status = str(candidate.get("status", "candidate"))
                author = str(candidate.get("author", ""))
                item = QListWidgetItem(f"  {name} | {status} | {author}")
                item.setData(Qt.ItemDataRole.UserRole, ("release", str(name)))
                self.history_list.addItem(item)

        if self._workspace_change_log:
            self.history_list.addItem(QListWidgetItem("---- recent changes ----"))
            for idx, row in enumerate(reversed(self._workspace_change_log[-12:]), start=1):
                actor = str(row.get("user", "unknown"))
                event = str(row.get("event", "event"))
                summary = str(row.get("details_summary", ""))
                item = QListWidgetItem(f"  {actor} | {event} | {summary}")
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    ("change_event", int(len(self._workspace_change_log) - idx)),
                )
                self.history_list.addItem(item)

        if os.path.isdir(self._snapshot_store_dir):
            try:
                files = [
                    os.path.join(self._snapshot_store_dir, f)
                    for f in os.listdir(self._snapshot_store_dir)
                    if str(f).lower().endswith(".json")
                ]
                files.sort(key=lambda p: os.path.getmtime(p))
            except Exception:
                files = []
            if files:
                self.history_list.addItem(QListWidgetItem("---- saved snapshot paths ----"))
                for snap_path in reversed(files[-8:]):
                    item = QListWidgetItem(f"  {snap_path}")
                    item.setData(Qt.ItemDataRole.UserRole, ("snapshot_path", str(snap_path)))
                    self.history_list.addItem(item)

        self.history_undo5_btn.setEnabled(bool(self._undo_stack))
        self.history_redo5_btn.setEnabled(bool(self._redo_stack))
        self.history_save_snapshot_btn.setEnabled(bool(self.current_schedule))
        self.history_load_snapshot_btn.setEnabled(self.inst is not None)

    def _undo_many(self, steps: int) -> None:
        count = max(0, min(int(steps), len(self._undo_stack)))
        for _ in range(count):
            self.on_undo()
        if count > 1:
            self.set_status(f"Undo applied x{count}")

    def _redo_many(self, steps: int) -> None:
        count = max(0, min(int(steps), len(self._redo_stack)))
        for _ in range(count):
            self.on_redo()
        if count > 1:
            self.set_status(f"Redo applied x{count}")

    def on_history_item_activated(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        kind, steps = payload
        if str(kind) == "snapshot_path":
            self._load_history_snapshot_path(str(steps))
            return
        if str(kind) == "branch":
            branch = self._branches.get(str(steps))
            if not isinstance(branch, dict):
                return
            self._push_undo_state()
            schedule = {
                int(a_id): dict(info)
                for a_id, info in dict(branch.get("current_schedule", {}) or {}).items()
                if isinstance(info, dict)
            }
            self.current_schedule = schedule
            self._active_branch_name = str(steps)
            self._bump_schedule_revision()
            self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
            self._sync_instance_staff_from_schedule(self.current_schedule)
            self._sync_locks_to_instance()
            self.update_table()
            self.update_quality_summary()
            self._refresh_history_buttons()
            self._append_audit_log("named_branch_loaded", {"name": str(steps), "source": "history"})
            self.set_status(f"Loaded branch {steps} from history.")
            return
        if str(kind) == "release":
            candidate = self._release_candidates.get(str(steps))
            if not isinstance(candidate, dict):
                return
            self._push_undo_state()
            schedule = {
                int(a_id): dict(info)
                for a_id, info in dict(candidate.get("schedule", {}) or {}).items()
                if isinstance(info, dict)
            }
            self.current_schedule = schedule
            self._bump_schedule_revision()
            self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
            self._sync_instance_staff_from_schedule(self.current_schedule)
            self._sync_locks_to_instance()
            self.update_table()
            self.update_quality_summary()
            self._refresh_history_buttons()
            self._append_audit_log(
                "release_candidate_loaded",
                {"name": str(steps), "source": "history"},
            )
            self.set_status(f"Loaded release candidate {steps} from history.")
            return
        if str(kind) == "change_event":
            try:
                idx = int(steps)
            except Exception:
                return
            if idx < 0 or idx >= len(self._workspace_change_log):
                return
            row = self._workspace_change_log[idx]
            QMessageBox.information(
                self,
                "Change Event",
                "\n".join(
                    [
                        f"Time: {row.get('timestamp_utc', '')}",
                        f"Actor: {row.get('user', '')}",
                        f"Event: {row.get('event', '')}",
                        f"Details: {json.dumps(row.get('details', {}), ensure_ascii=False)}",
                    ]
                ),
            )
            return
        try:
            steps_i = int(steps)
        except Exception:
            steps_i = 0
        if str(kind) == "undo" and steps_i > 0:
            self._undo_many(steps_i)
            return
        if str(kind) == "redo" and steps_i > 0:
            self._redo_many(steps_i)
            return

    def on_save_history_snapshot(self) -> None:
        if self.inst is None or not self.current_schedule:
            return
        snapshot_dir = self._ensure_snapshot_store_dir()
        default_name = (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "_snapshot.json"
        )
        default_path = os.path.join(snapshot_dir, default_name)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save history snapshot",
            default_path,
            "JSON files (*.json)",
        )
        if not path:
            return
        payload = {
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            "instance": instance_to_json(self.inst),
            "base_schedule": {
                str(int(a_id)): dict(info)
                for a_id, info in self.base_schedule.items()
                if isinstance(info, dict)
            },
            "state": self._state_to_json_ready(self._snapshot_state()),
            "undo": [
                self._state_to_json_ready(s)
                for s in self._undo_stack[-60:]
                if isinstance(s, dict)
            ],
            "redo": [
                self._state_to_json_ready(s)
                for s in self._redo_stack[-60:]
                if isinstance(s, dict)
            ],
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
            self.set_status(f"History snapshot saved: {path}")
            self._append_audit_log("history_snapshot_saved", {"path": str(path)})
            self._refresh_history_view()
        except Exception as exc:
            QMessageBox.critical(self, "Snapshot error", str(exc))

    def on_load_history_snapshot(self) -> None:
        snapshot_dir = self._ensure_snapshot_store_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load history snapshot",
            snapshot_dir,
            "JSON files (*.json)",
        )
        if not path:
            return
        self._load_history_snapshot_path(str(path))

    def _load_history_snapshot_path(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("Snapshot must be a JSON object.")
            inst_raw = payload.get("instance")
            if not isinstance(inst_raw, dict):
                raise ValueError("Snapshot is missing instance data.")
            self.inst = instance_from_json(inst_raw)
            base_raw = payload.get("base_schedule", {})
            self.base_schedule = {
                int(a_id): dict(info)
                for a_id, info in (base_raw.items() if isinstance(base_raw, dict) else [])
                if isinstance(info, dict)
            }
            state_raw = payload.get("state", {})
            state = self._state_from_json_ready(
                state_raw if isinstance(state_raw, dict) else {}
            )
            self.current_schedule = {
                int(a_id): dict(info)
                for a_id, info in (state.get("current_schedule") or {}).items()
            }
            self.locked_activities = {
                int(a_id): dict(lock)
                for a_id, lock in (state.get("locked_activities") or {}).items()
            }
            held = state.get("held_activity_id")
            self.held_activity_id = int(held) if held is not None else None
            self._undo_stack = [
                self._state_from_json_ready(s)
                for s in (payload.get("undo") or [])
                if isinstance(s, dict)
            ]
            self._redo_stack = [
                self._state_from_json_ready(s)
                for s in (payload.get("redo") or [])
                if isinstance(s, dict)
            ]
            self._bump_schedule_revision()
            self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
            self._sync_instance_staff_from_schedule(self.current_schedule)
            self._sync_locks_to_instance()
            self._load_constraint_controls_from_instance(self.inst)
            self.populate_weeks()
            self.update_entities()
            self.update_table()
            self.update_quality_summary()
            self._refresh_history_buttons()
            self.set_status(f"History snapshot loaded: {path}")
            self._append_audit_log("history_snapshot_loaded", {"path": str(path)})
        except Exception as exc:
            QMessageBox.critical(self, "Snapshot error", str(exc))

    def on_show_snapshot_dir(self) -> None:
        path = self._ensure_snapshot_store_dir()
        QMessageBox.information(
            self,
            "Snapshot folder",
            f"History snapshot folder:\n{path}",
        )

    def _snapshot_state(self) -> Dict[str, Any]:
        return {
            "current_schedule": self._clone_schedule(),
            "locked_activities": {
                int(a_id): dict(lock) for a_id, lock in self.locked_activities.items()
            },
            "held_activity_id": self.held_activity_id,
        }

    def _restore_state(self, state: Dict[str, Any], status: str) -> None:
        self.current_schedule = {
            int(a_id): info.copy()
            for a_id, info in (state.get("current_schedule") or {}).items()
        }
        self.locked_activities = {
            int(a_id): dict(lock)
            for a_id, lock in (state.get("locked_activities") or {}).items()
        }
        held = state.get("held_activity_id")
        self.held_activity_id = int(held) if held is not None else None
        self._bump_schedule_revision()
        self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status(status)
        self._save_persistent_history()

    def _reset_history(self) -> None:
        self._undo_stack = []
        self._redo_stack = []
        self._refresh_history_buttons()
        self._save_persistent_history()

    def _push_undo_state(self) -> None:
        if self.inst is None:
            return
        self._undo_stack.append(self._snapshot_state())
        if len(self._undo_stack) > 120:
            self._undo_stack.pop(0)
        self._redo_stack = []
        self._refresh_history_buttons()
        self._save_persistent_history()

    def _refresh_history_buttons(self) -> None:
        self.undo_button.setEnabled(bool(self._undo_stack))
        self.redo_button.setEnabled(bool(self._redo_stack))
        self.revert_button.setEnabled(bool(self.base_schedule))
        self.conflicts_button.setEnabled(bool(self.current_schedule))
        self._refresh_history_view()

    def on_undo(self) -> None:
        if not self._undo_stack:
            self.set_status("Nothing to undo")
            return
        current = self._snapshot_state()
        prev = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._restore_state(prev, "Undo applied")
        self._refresh_history_buttons()
        self._append_audit_log("undo_applied", {"undo_depth": len(self._undo_stack)})

    def on_redo(self) -> None:
        if not self._redo_stack:
            self.set_status("Nothing to redo")
            return
        current = self._snapshot_state()
        nxt = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._restore_state(nxt, "Redo applied")
        self._refresh_history_buttons()
        self._append_audit_log("redo_applied", {"redo_depth": len(self._redo_stack)})

    def on_revert_to_base(self) -> None:
        if not self.base_schedule:
            self.set_status("No base solution to revert to")
            return
        base_errors = self._validate_schedule_hard_errors(
            self.base_schedule, require_all=False
        )
        if base_errors:
            sample = "\n".join(f"- {line}" for line in base_errors[:10])
            QMessageBox.warning(
                self,
                "Revert blocked",
                "Base schedule currently has hard conflicts and was not applied.\n\n"
                f"Conflicts: {len(base_errors)}\n{sample}",
            )
            self.set_status(
                f"Revert blocked: base has {len(base_errors)} hard conflicts"
            )
            return
        self._push_undo_state()
        self.current_schedule = {a_id: info.copy() for a_id, info in self.base_schedule.items()}
        self._set_manual_highlight_base(self.current_schedule)
        self.locked_activities = {}
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._sync_instance_activity_weeks_from_schedule(self.current_schedule)
        self._sync_instance_staff_from_schedule(self.current_schedule)
        self._sync_locks_to_instance()
        self.update_table()
        self.update_quality_summary()
        self.set_status("Reverted to base schedule")
        self._refresh_history_buttons()
