from __future__ import annotations

from ui.window_runtime import *  # noqa: F401,F403
from ui.window_runtime import _window_global


class WindowIOMixin:

    def on_show_audit_log_path(self) -> None:
        QMessageBox.information(
            self,
            "Audit log",
            f"Audit log file:\n{self._audit_log_path}",
        )
        self.set_status(f"Audit log: {self._audit_log_path}")

    def on_show_change_history(self) -> None:
        rows = list(reversed(self._workspace_change_log))
        if not rows:
            QMessageBox.information(
                self,
                "Workspace Change History",
                "No workspace change history has been recorded yet.",
            )
            return
        dlg = ChangeHistoryDialog(self, rows)
        dlg.exec()
        self.set_status("Viewed workspace change history")

    def on_show_about(self) -> None:
        QMessageBox.information(
            self,
            f"About {self._effective_branding().get('short_name', APP_SHORT_NAME)}",
            "\n".join(about_lines(self._effective_branding())),
        )
        self.set_status(f"About {self._effective_branding().get('short_name', APP_SHORT_NAME)}")

    def on_check_updates(self) -> None:
        manifest_source = str(
            self._runtime_settings.get("update_manifest_path")
            or _resource_path("docs", "portal", "update_manifest.json")
        )
        if not os.path.isabs(manifest_source) and not manifest_source.startswith(("http://", "https://")):
            manifest_source = _resource_path(manifest_source)
        try:
            result = check_for_updates(
                current_version=str(APP_VERSION),
                manifest_source=manifest_source,
                channel=str(self._runtime_settings.get("update_channel", "stable") or "stable"),
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Update check error", str(exc))
            return
        status = (
            f"Update available: {result['latest_version']}"
            if bool(result.get("available", False))
            else f"Up to date ({result['current_version']})"
        )
        msg = [
            f"Channel: {result.get('channel', 'stable')}",
            f"Current: {result.get('current_version', APP_VERSION)}",
            f"Latest: {result.get('latest_version', APP_VERSION)}",
            f"Download: {result.get('download_url', '') or 'n/a'}",
            f"Notes: {result.get('notes', '') or 'No release notes provided.'}",
        ]
        QMessageBox.information(self, "Update Channel", "\n".join(msg))
        self._append_audit_log("update_channel_checked", dict(result))
        self.set_status(status)

    def on_set_update_channel(self) -> None:
        choice, ok = QInputDialog.getItem(
            self,
            "Update Channel",
            "Channel:",
            ["stable", "preview"],
            0 if str(self._runtime_settings.get("update_channel", "stable")) == "stable" else 1,
            False,
        )
        if not ok:
            return
        self._runtime_settings["update_channel"] = str(choice)
        save_runtime_settings(self._runtime_paths["settings"], self._runtime_settings)
        self._append_audit_log("update_channel_set", {"channel": str(choice)})
        self.set_status(f"Update channel set to {choice}")

    def on_toggle_crash_reports_opt_in(self) -> None:
        current = bool(self._runtime_settings.get("crash_reports_opt_in", False))
        self._runtime_settings["crash_reports_opt_in"] = not current
        save_runtime_settings(self._runtime_paths["settings"], self._runtime_settings)
        state = "enabled" if self._runtime_settings["crash_reports_opt_in"] else "disabled"
        self._append_audit_log("crash_reporting_toggled", {"state": state})
        self.set_status(f"Crash reports {state}")

    def on_toggle_telemetry_opt_in(self) -> None:
        current = bool(self._runtime_settings.get("telemetry_opt_in", False))
        self._runtime_settings["telemetry_opt_in"] = not current
        save_runtime_settings(self._runtime_paths["settings"], self._runtime_settings)
        state = "enabled" if self._runtime_settings["telemetry_opt_in"] else "disabled"
        self._append_audit_log("telemetry_toggled", {"state": state})
        self.set_status(f"Telemetry {state}")

    def on_show_runtime_log_folder(self) -> None:
        folder = str(self._runtime_paths.get("root", os.path.expanduser("~")))
        QMessageBox.information(
            self,
            "Runtime Logs",
            f"Runtime state folder:\n{folder}",
        )
        self.set_status(f"Runtime folder: {folder}")

    def on_export_support_bundle(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export support bundle",
            "planora_support_bundle.zip",
            "ZIP (*.zip)",
        )
        if not path:
            return
        extra_files: Dict[str, str] = {}
        if self.inst is not None:
            extra_files["workspace/current_schedule.json"] = json.dumps(
                self.current_schedule,
                indent=2,
                sort_keys=True,
            )
            extra_files["workspace/meta.json"] = json.dumps(
                self._workspace_meta(),
                indent=2,
                sort_keys=True,
            )
        try:
            bundle = collect_support_bundle(
                path,
                runtime_paths=self._runtime_paths,
                settings=self._runtime_settings,
                metadata={"window_title": self.windowTitle()},
                extra_files=extra_files,
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Support bundle error", str(exc))
            return
        self._append_audit_log("support_bundle_exported", {"path": str(bundle)})
        self.set_status(f"Support bundle exported to {bundle}")

    def on_export_quality_report(self) -> None:
        if self.inst is None or not self.current_schedule:
            self.set_status("No schedule to report")
            return
        folder = QFileDialog.getExistingDirectory(
            self,
            "Export quality report",
            "",
        )
        if not folder:
            return
        try:
            report = build_stakeholder_quality_report(
                self.inst,
                self.current_schedule,
                branding=self._effective_branding(),
                baseline_schedule=self.base_schedule or None,
            )
            outputs = write_stakeholder_quality_report(folder, report)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Quality report error", str(exc))
            return
        self._append_audit_log("quality_report_exported", dict(outputs))
        self.set_status(f"Quality report exported to {outputs.get('markdown', folder)}")

    def on_export_calendar_feeds(self) -> None:
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return
        path = QFileDialog.getExistingDirectory(
            self,
            "Export calendar feeds (choose folder)",
            "",
        )
        if not path:
            return
        try:
            export_fn = _window_global("export_calendar_feeds", export_calendar_feeds)
            manifest = export_fn(self.inst, self.current_schedule, path)
            feed_count = sum(
                len(v) for v in (manifest.get("feeds", {}) or {}).values() if isinstance(v, list)
            )
            self.set_status(f"Calendar feeds exported ({feed_count} files)")
            self._append_audit_log(
                "calendar_feeds_exported",
                {"path": str(path), "feed_files": int(feed_count)},
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(exc))

    def _export_connector_csv(
        self,
        *,
        title: str,
        default_name: str,
        writer: Any,
        audit_event: str,
    ) -> None:
        if self.inst is None:
            self.set_status("No instance to export")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            default_name,
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            writer(self.inst, path)
            self._append_audit_log(audit_event, {"path": str(path)})
            self.set_status(f"Connector export written to {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Connector export error", str(exc))
            self.set_status("Connector export error")

    def on_export_sis_csv(self) -> None:
        connector = SISCsvConnector()
        self._export_connector_csv(
            title="Export SIS CSV",
            default_name="sis_courses.csv",
            writer=connector.export_courses,
            audit_event="connector_export_sis_csv",
        )

    def on_export_erp_csv(self) -> None:
        connector = ERPCsvConnector()
        self._export_connector_csv(
            title="Export ERP CSV",
            default_name="erp_staff_ownership.csv",
            writer=connector.export_staff_ownership,
            audit_event="connector_export_erp_csv",
        )

    def on_export_lms_csv(self) -> None:
        connector = LMSCsvConnector()
        self._export_connector_csv(
            title="Export LMS CSV",
            default_name="lms_group_enrollments.csv",
            writer=connector.export_group_enrollments,
            audit_event="connector_export_lms_csv",
        )

    def _read_csv_preview_rows(
        self, path: str, *, max_rows: int = 20
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        import csv

        headers: List[str] = []
        rows: List[Dict[str, Any]] = []
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = [str(h) for h in (reader.fieldnames or [])]
            for idx, row in enumerate(reader):
                if idx >= int(max_rows):
                    break
                rows.append({str(k): row.get(k) for k in headers})
        return headers, rows

    def _load_validated_schedule(self, schedule: Dict[int, Dict[str, Any]], *, source: str) -> None:
        if self.inst is None:
            return
        filtered = {}
        missing = 0
        invalid = 0
        inst = self.inst
        for a_id, info in schedule.items():
            if int(a_id) not in inst.activities:
                missing += 1
                continue
            act = inst.activities[int(a_id)]
            day = info.get("day")
            slot = int(info.get("slot", -1))
            dur = int(info.get("duration", act.duration))
            staff_id = info.get("staff_id")
            week = int(info.get("week", act.week))
            if day not in inst.days:
                invalid += 1
                continue
            if slot < 0 or slot + dur > inst.slots_per_day:
                invalid += 1
                continue
            if dur not in (1, 2, 3):
                invalid += 1
                continue
            if staff_id is not None and int(staff_id) not in inst.staff:
                invalid += 1
                continue
            if act.kind == "LEC" and staff_id is not None and not inst.staff.get(int(staff_id)).is_prof:
                invalid += 1
                continue
            if act.kind != "LEC" and staff_id is not None and inst.staff.get(int(staff_id)).is_prof:
                invalid += 1
                continue
            filtered[int(a_id)] = dict(info)

        self.base_schedule = filtered
        self.current_schedule = {a_id: info.copy() for a_id, info in filtered.items()}
        self._set_manual_highlight_base(self.current_schedule)
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        errors = validate_schedule_against_instance(
            self.inst,
            self.current_schedule,
            strict_rooms=False,
            require_all_activities=False,
        )
        if errors:
            msg = "Schedule violates hard rules:\n" + "\n".join(f"- {e}" for e in errors[:20])
            if len(errors) > 20:
                msg += f"\n... and {len(errors) - 20} more"
            QMessageBox.critical(self, "Invalid schedule", msg)
            self.base_schedule = {}
            self._set_manual_highlight_base({})
            self.current_schedule = {}
            self.held_activity_id = None
            self._bump_schedule_revision()
            self.clear_table()
            self.set_status("Load error")
            return
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        msg = f"Loaded schedule {source}"
        if missing:
            msg += f" ({missing} activities ignored)"
        if invalid:
            msg += f" ({invalid} invalid rows skipped)"
        self.set_status(msg)
        self._append_audit_log(
            "schedule_imported",
            {
                "source": str(source),
                "loaded_rows": int(len(self.current_schedule)),
                "missing_rows": int(missing),
                "invalid_rows": int(invalid),
            },
        )
        self._save_persistent_history()

    def on_import_schedule_wizard(self) -> None:
        if self.inst is None:
            self.set_status("Load instance first")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import schedule (wizard)",
            "",
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            headers, preview_rows = self._read_csv_preview_rows(path)
        except Exception as exc:
            QMessageBox.critical(self, "Import error", str(exc))
            return
        if not headers:
            QMessageBox.warning(self, "Import error", "No CSV headers found.")
            return
        dialog_cls = _window_global("ImportScheduleWizardDialog", ImportScheduleWizardDialog)
        dlg = dialog_cls(
            self,
            headers,
            preview_rows,
            default_mapping=self._last_import_mapping,
            default_group_separator=self._last_group_separator,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self._last_import_mapping = dict(dlg.selected_mapping())
            self._last_group_separator = str(dlg.group_separator())
            read_mapped = _window_global("read_schedule_csv_mapped", read_schedule_csv_mapped)
            schedule = read_mapped(
                path,
                field_map=self._last_import_mapping,
                group_separator=self._last_group_separator,
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Import error", str(exc))
            return
        self._load_validated_schedule(schedule, source=path)

    def on_import_timetable_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import timetable CSV",
            "",
            "CSV files (*.csv)",
        )
        if not path:
            return
        try:
            headers, preview_rows = self._read_csv_preview_rows(path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Import error", str(exc))
            self.set_status("Import error")
            return
        if not headers:
            QMessageBox.warning(self, "Import error", "No CSV headers found.")
            self.set_status("Import error")
            return

        default_mapping = suggest_timetable_mapping(headers)
        dialog_cls = _window_global(
            "TimetableCsvImportWizardDialog", TimetableCsvImportWizardDialog
        )
        dlg = dialog_cls(
            self,
            headers,
            preview_rows,
            default_mapping=default_mapping,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.set_status("Import canceled")
            return
        field_map = dict(dlg.selected_mapping())
        transform_config = {}
        try:
            transform_config = dict(dlg.transform_config())
        except Exception:
            transform_config = {}

        teaching_load_path: str | None = None
        load_staff = QMessageBox.question(
            self,
            "Use teaching-load assignments?",
            "Optionally select an XLSX teaching-load workbook to map real lecturers and TAs.\n"
            "Choose No to use balanced synthetic staff pools.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if load_staff == QMessageBox.StandardButton.Yes:
            selected, _ = QFileDialog.getOpenFileName(
                self,
                "Select teaching-load workbook",
                "",
                "Excel workbook (*.xlsx)",
            )
            if str(selected).lower().endswith(".xlsx"):
                teaching_load_path = str(selected)

        try:
            self.set_status("Importing timetable CSV...")
            import_fn = _window_global("import_timetable_csv", import_timetable_csv)
            inst, schedule, meta = import_fn(
                path,
                lock_imported=False,
                field_map=field_map,
                transform_config=transform_config,
                teaching_load_path=teaching_load_path,
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Import error", str(exc))
            self.set_status("Import error")
            return

        preview_lines = [
            f"Source rows: {int(meta.get('source_events', 0))}",
            f"Activities after merge: {int(meta.get('activities_after_shared_event_merge', len(schedule)))}",
            f"Groups: {int(meta.get('groups', len(inst.groups)))}",
            f"Courses: {int(meta.get('courses', len(inst.courses)))}",
            f"Rooms: {int(meta.get('rooms', len(inst.rooms)))}",
            f"Teaching-load course matches: {int(meta.get('teaching_load_matches', 0))}",
            f"Soft penalty: {int(meta.get('soft_penalty', 0))}",
            f"Hard conflicts: {int(meta.get('validation_error_count', 0))}",
        ]
        decision = QMessageBox.question(
            self,
            "Import timetable CSV?",
            "Import preview:\n\n"
            + "\n".join(preview_lines)
            + "\n\nThe imported placements will remain unlocked so Solve/Repair can move them.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if decision != QMessageBox.StandardButton.Yes:
            self.set_status("Import canceled")
            return

        self.inst = inst
        self.locked_activities = dict(getattr(inst, "locked_activities", {}) or {})
        self.base_schedule = {int(a_id): dict(info) for a_id, info in schedule.items()}
        self.current_schedule = {int(a_id): dict(info) for a_id, info in schedule.items()}
        self.held_activity_id = None
        self._set_manual_highlight_base(self.current_schedule)
        self._bump_schedule_revision()
        self._reset_history()
        self._load_constraint_controls_from_instance(self.inst)
        self._refresh_product_scenario_from_instance()
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self._refresh_history_view()
        self._refresh_history_buttons()
        self._append_audit_log(
            "timetable_csv_imported",
            {
                "path": str(path),
                "teaching_load_path": str(teaching_load_path or ""),
                "activities": int(meta.get("activities_after_shared_event_merge", 0)),
                "soft_penalty": int(meta.get("soft_penalty", 0)),
                "hard_conflicts": int(meta.get("validation_error_count", 0)),
            },
        )
        self._save_persistent_history()
        conflicts = int(meta.get("validation_error_count", 0))
        penalty = int(meta.get("soft_penalty", 0))
        self.set_status(
            f"Imported timetable CSV: {len(schedule)} activities, soft penalty {penalty}, hard conflicts {conflicts}"
        )
        if conflicts:
            preview = "\n".join(str(err) for err in list(meta.get("validation_errors", []) or [])[:8])
            QMessageBox.warning(
                self,
                "Imported with conflicts",
                "The timetable was imported and left unlocked so Solve/Improve can repair it.\n\n"
                f"Hard conflicts: {conflicts}\n"
                f"Soft penalty: {penalty}\n\n"
                + (preview if preview else "Open Conflicts for details."),
            )
        save_decision = QMessageBox.question(
            self,
            "Save imported scenario?",
            "Save this imported CSV as a reusable scheduler scenario now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if save_decision == QMessageBox.StandardButton.Yes:
            out_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save imported scenario",
                "imported_timetable_scenario.json",
                "Scenario (*.json *.pkl)",
            )
            if out_path:
                try:
                    write_scenario(
                        out_path,
                        self.inst,
                        self.current_schedule,
                        meta={
                            "source_import": dict(meta),
                            "operator_name": str(self._operator_name),
                        },
                    )
                    self.set_status(f"Imported timetable saved to {out_path}")
                except Exception as exc:
                    traceback.print_exc()
                    QMessageBox.warning(self, "Save scenario error", str(exc))

    def on_export(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export group schedules",
            "timetable.docx",
            "Word document (*.docx)",
        )
        if not path:
            return

        try:
            self.set_status("Exporting...")
            export_docx_service(
                self.inst,
                self.current_schedule,
                path,
                branding=self._effective_branding(),
            )
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(e))
            self.set_status("Export error")
            return

        self.set_status(f"Exported to {path}")

    def on_export_pdf(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export group schedules (PDF)",
            "timetable.pdf",
            "PDF document (*.pdf)",
        )
        if not path:
            return

        try:
            self.set_status("Exporting PDF...")
            export_pdf_service(
                self.inst,
                self.current_schedule,
                path,
                branding=self._effective_branding(),
            )
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(e))
            self.set_status("Export error")
            return

        self.set_status(f"Exported to {path}")

    def on_export_reports(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return

        path = QFileDialog.getExistingDirectory(
            self,
            "Export CSV reports (choose folder)",
            "",
        )
        if not path:
            return

        try:
            self.set_status("Writing reports...")
            export_reports_service(
                self.inst,
                self.current_schedule,
                path,
                branding=self._effective_branding(),
                baseline_schedule=self.base_schedule or None,
            )
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(e))
            self.set_status("Export error")
            return

        self.set_status(f"Reports written to {path}")

    def on_export_csv(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export schedule (CSV)",
            "schedule.csv",
            "CSV files (*.csv)",
        )
        if not path:
            return

        try:
            self.set_status("Exporting CSV...")
            export_fn = _window_global("export_schedule_to_csv", export_schedule_to_csv)
            export_fn(self.inst, self.current_schedule, path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(e))
            self.set_status("Export error")
            return

        self.set_status(f"Exported to {path}")

    def on_export_ics(self):
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return

        path = QFileDialog.getExistingDirectory(
            self,
            "Export ICS calendars (choose folder)",
            "",
        )
        if not path:
            return

        try:
            self.set_status("Exporting ICS...")
            export_groups = _window_global("export_groups_ics_per_id", export_groups_ics_per_id)
            export_staff = _window_global("export_staff_ics_per_id", export_staff_ics_per_id)
            export_rooms = _window_global("export_rooms_ics_per_id", export_rooms_ics_per_id)
            export_groups(self.inst, self.current_schedule, path)
            export_staff(self.inst, self.current_schedule, path)
            export_rooms(self.inst, self.current_schedule, path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Export error", str(e))
            self.set_status("Export error")
            return

        self.set_status(f"ICS exported to {path}")

    def on_save_project(self):
        if self.inst is None:
            self.set_status("No instance to save")
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save project",
            "project.json",
            "Project (*.json *.pkl *.db *.sqlite)",
        )
        if not path:
            return

        try:
            self.set_status("Saving project...")
            # Ensure locks are persisted
            self.inst.locked_activities = dict(self.locked_activities)
            schedule = self.current_schedule or {}
            meta = {"source": "ui", **self._workspace_meta()}
            save_legacy_project(path, self.inst, schedule, meta=meta)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Save error", str(e))
            self.set_status("Save error")
            return

        self.set_status(f"Saved to {path}")

    def on_save_product_scenario(self) -> None:
        if self.inst is None and self.product_scenario is None:
            self.set_status("No scenario to save")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Save {APP_SHORT_NAME} product scenario",
            "planora_scenario.json",
            "Product Scenario (*.json)",
        )
        if not path:
            return
        try:
            self.set_status("Saving product scenario...")
            if self.inst is not None:
                self._refresh_product_scenario_from_instance()
            scenario = self.product_scenario
            if scenario is None:
                raise ValueError("No product scenario available")
            save_product_scenario(path, scenario)
            self._append_audit_log("product_scenario_saved", {"path": str(path)})
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Save error", str(exc))
            self.set_status("Save error")
            return
        self.set_status(f"Product scenario saved to {path}")

    def _collect_institution_template_payload(self) -> Dict[str, Any]:
        custom_config = self._collect_custom_generation_config()
        hard, soft = self._collect_constraint_settings()
        return {
            "name": getattr(self.product_scenario, "metadata", None).name
            if self.product_scenario is not None
            else "Institution Template",
            "branding": {
                **self._effective_branding(),
            },
            "objective_profile": str(
                self.objective_profile_combo.currentData() or "balanced"
            ),
            "constraints": {
                "hard": dict(hard),
                "soft": dict(soft),
            },
            "generator_defaults": dict(custom_config),
            "import_defaults": {
                "mapping": dict(self._last_import_mapping or {}),
                "group_separator": str(self._last_group_separator or ";"),
            },
        }

    def _apply_institution_template_payload(self, payload: Dict[str, Any]) -> None:
        merged = apply_institution_template(
            payload,
            current_config=self._collect_institution_template_payload(),
        )
        self._institution_template = dict(merged)
        self._branding_profile = branding_from_institution_template(merged)
        self._apply_branding_profile()
        objective_profile = str(merged.get("objective_profile", "balanced") or "balanced")
        idx = self.objective_profile_combo.findData(objective_profile)
        if idx >= 0:
            self.objective_profile_combo.setCurrentIndex(idx)
        constraints = dict(merged.get("constraints", {}) or {})
        hard = dict(constraints.get("hard", {}) or {})
        soft = dict(constraints.get("soft", {}) or {})
        if hard:
            self.hard_week1_cb.setChecked(bool(hard.get("week1_lectures_only", True)))
            self.hard_block_prof_cb.setChecked(
                bool(hard.get("enforce_block_professor_rules", True))
            )
            self.hard_staff_daily_cb.setChecked(
                bool(hard.get("enforce_staff_daily_caps", True))
            )
            self.hard_staff_weekly_cb.setChecked(
                bool(hard.get("enforce_staff_weekly_caps", True))
            )
            self.hard_room_availability_cb.setChecked(
                bool(hard.get("enforce_room_availability", True))
            )
        for key, spin in self.soft_weight_spins.items():
            if key in soft:
                try:
                    spin.setValue(int(soft[key]))
                except Exception:
                    continue
        generator_defaults = merged.get("generator_defaults")
        if isinstance(generator_defaults, dict):
            self._apply_custom_generation_config(generator_defaults)
        import_defaults = dict(merged.get("import_defaults", {}) or {})
        self._last_import_mapping = {
            str(k): str(v)
            for k, v in dict(import_defaults.get("mapping", {}) or {}).items()
        }
        self._last_group_separator = str(
            import_defaults.get("group_separator", ";") or ";"
        )

    def on_save_institution_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save institution template",
            "institution_template.json",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            save_institution_template(path, self._collect_institution_template_payload())
            self.set_status(f"Institution template saved to {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Template error", str(exc))
            self.set_status("Template save error")

    def on_load_institution_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load institution template",
            "",
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            payload = load_institution_template(path)
            self._apply_institution_template_payload(payload)
            self._save_persistent_history()
            self.set_status(f"Institution template loaded from {path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Template error", str(exc))
            self.set_status("Template load error")

    def on_apply_white_label_profile(self) -> None:
        institution_name, ok = QInputDialog.getText(
            self,
            "White-Label Profile",
            "Institution name:",
            text=str(self._institution_template.get("name", "") if isinstance(self._institution_template, dict) else ""),
        )
        if not ok or not str(institution_name).strip():
            return
        owner_name, ok_owner = QInputDialog.getText(
            self,
            "White-Label Profile",
            "Owner / publisher:",
            text=str(self._operator_name or APP_OWNER_NAME),
        )
        if not ok_owner:
            return
        self._branding_profile = white_label_profile_for_institution(
            institution_name=str(institution_name).strip(),
            owner_name=str(owner_name).strip() or APP_OWNER_NAME,
        )
        if self._institution_template is None:
            self._institution_template = {}
        self._institution_template["name"] = str(institution_name).strip()
        self._institution_template["branding"] = dict(self._branding_profile)
        self._apply_branding_profile()
        self._append_audit_log(
            "white_label_profile_applied",
            {"institution": str(institution_name).strip()},
        )
        self._save_persistent_history()
        self.set_status(f"White-label profile applied for {str(institution_name).strip()}")

    def on_set_operator_name(self) -> None:
        value, ok = QInputDialog.getText(
            self,
            "Operator Name",
            "Current operator:",
            text=str(self._operator_name or ""),
        )
        if not ok:
            return
        previous = str(self._operator_name or "unknown")
        self._operator_name = str(value or "").strip() or "unknown"
        self._append_audit_log(
            "operator_changed",
            {"previous": previous, "current": self._operator_name},
        )
        self._save_persistent_history()
        self.set_status(f"Operator set to {self._operator_name}")

    def on_save_import_export_template(self) -> None:
        default_name = "Default"
        if isinstance(self._institution_template, dict):
            default_name = str(self._institution_template.get("name", default_name) or default_name)
        elif self.product_scenario is not None:
            default_name = str(self.product_scenario.metadata.name or default_name)
        institution, ok = QInputDialog.getText(
            self,
            "Save Import/Export Template",
            "Institution/profile name:",
            text=default_name,
        )
        if not ok:
            return
        payload = {
            "institution_name": str(institution or "").strip() or default_name,
            "operator_name": str(self._operator_name),
            "import_mapping": dict(self._last_import_mapping or {}),
            "group_separator": str(self._last_group_separator or ";"),
        }
        try:
            save_import_export_template_profile(
                self._import_export_template_path,
                institution_name=str(payload["institution_name"]),
                template=payload,
            )
            self._append_audit_log(
                "import_export_template_saved",
                {
                    "institution_name": str(payload["institution_name"]),
                    "path": str(self._import_export_template_path),
                },
            )
            self._save_persistent_history()
            self.set_status(
                "Import/export template saved to "
                f"{self._import_export_template_path} for {payload['institution_name']}"
            )
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Template error", str(exc))

    def on_load_import_export_template(self) -> None:
        try:
            profiles = list_import_export_template_profiles(self._import_export_template_path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Template error", str(exc))
            return
        if not profiles:
            QMessageBox.information(
                self,
                "Import/Export Templates",
                "No saved import/export template profiles were found yet.",
            )
            return
        choice, ok = QInputDialog.getItem(
            self,
            "Load Import/Export Template",
            "Institution/profile:",
            profiles,
            0,
            False,
        )
        if not ok:
            return
        try:
            payload = load_import_export_template_profile(
                self._import_export_template_path,
                institution_name=str(choice),
            )
            self._last_import_mapping = {
                str(k): str(v)
                for k, v in dict(payload.get("import_mapping", {}) or {}).items()
            }
            self._last_group_separator = str(
                payload.get("group_separator", self._last_group_separator) or self._last_group_separator
            )
            self._append_audit_log(
                "import_export_template_loaded",
                {
                    "institution_name": str(choice),
                    "path": str(self._import_export_template_path),
                },
            )
            self._save_persistent_history()
            self.set_status(f"Import/export template loaded for {choice}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Template error", str(exc))

    def on_save_named_branch(self) -> None:
        if not self.current_schedule:
            self.set_status("No schedule to branch")
            return
        dlg = BranchMetadataDialog(
            self,
            title="Save Named Branch",
            default_name=self._active_branch_name or "",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, description = dlg.values()
        branch = create_branch(
            name=str(name),
            author=str(self._operator_name),
            description=str(description),
            base_schedule=self.base_schedule or self.current_schedule,
            current_schedule=self.current_schedule,
        )
        self._branches[str(name)] = dict(branch)
        self._active_branch_name = str(name)
        self._refresh_history_view()
        self._append_audit_log("named_branch_saved", {"name": str(name)})
        self._save_persistent_history()
        self.set_status(f"Saved named branch {name}")

    def on_load_named_branch(self) -> None:
        if not self._branches:
            self.set_status("No named branches available")
            return
        names = sorted(self._branches.keys())
        choice, ok = QInputDialog.getItem(
            self,
            "Load Named Branch",
            "Branch:",
            names,
            0,
            False,
        )
        if not ok:
            return
        branch = self._branches.get(str(choice))
        if not isinstance(branch, dict):
            return
        self._push_undo_state()
        self.current_schedule = {
            int(a_id): dict(info)
            for a_id, info in dict(branch.get("current_schedule", {}) or {}).items()
            if isinstance(info, dict)
        }
        self._active_branch_name = str(choice)
        self._bump_schedule_revision()
        self.update_table()
        self.update_quality_summary()
        self._refresh_history_view()
        self._refresh_history_buttons()
        self._append_audit_log("named_branch_loaded", {"name": str(choice)})
        self.set_status(f"Loaded branch {choice}")

    def on_branch_merge_assistance(self) -> None:
        if not self._branches:
            self.set_status("No named branches available")
            return
        names = sorted(self._branches.keys())
        choice, ok = QInputDialog.getItem(
            self,
            "Branch Merge Assistance",
            "Branch:",
            names,
            0,
            False,
        )
        if not ok:
            return
        branch = self._branches.get(str(choice))
        if not isinstance(branch, dict):
            return
        summary = branch_merge_assistance(branch, self.current_schedule or {})
        branch.setdefault("merge_notes", []).append(
            {
                "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
                "target_branch": str(choice),
                "summary": dict(summary),
            }
        )
        self._branches[str(choice)] = dict(branch)
        self._append_audit_log(
            "branch_merge_assistance_prepared",
            {
                "branch": str(choice),
                "changed_time": int(summary.get("changed_time", 0)),
                "changed_room": int(summary.get("changed_room", 0)),
                "changed_staff": int(summary.get("changed_staff", 0)),
            },
        )
        self._save_persistent_history()
        QMessageBox.information(
            self,
            "Branch Merge Assistance",
            "\n".join(
                [
                    str(summary.get("merge_message", "")),
                    f"Missing in target: {len(summary.get('missing_in_other', []))}",
                    f"Missing in branch: {len(summary.get('missing_in_base', []))}",
                ]
            ),
        )
        self.set_status(f"Merge assistance prepared for branch {choice}")

    def on_create_release_candidate(self) -> None:
        if not self.current_schedule:
            self.set_status("No schedule to release")
            return
        dlg = BranchMetadataDialog(self, title="Create Release Candidate", default_name="rc-1")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, notes = dlg.values()
        candidate = create_release_candidate(
            name=str(name),
            author=str(self._operator_name),
            schedule=self.current_schedule,
            notes=str(notes),
        )
        self._release_candidates[str(name)] = dict(candidate)
        self._refresh_history_view()
        self._append_audit_log("release_candidate_created", {"name": str(name)})
        self._save_persistent_history()
        self.set_status(f"Release candidate {name} created")

    def on_publish_release_candidate(self) -> None:
        if not self._release_candidates:
            self.set_status("No release candidates available")
            return
        names = sorted(self._release_candidates.keys())
        choice, ok = QInputDialog.getItem(
            self,
            "Publish Release Candidate",
            "Candidate:",
            names,
            0,
            False,
        )
        if not ok:
            return
        if bool(self._protected_baseline.get("protected", False)):
            approval = self._require_approval(
                action="publish_protected_baseline",
                details={"candidate": str(choice)},
            )
            if approval is None:
                self.set_status("Publish canceled: approval not granted")
                return
        candidate = publish_release_candidate(self._release_candidates[str(choice)])
        self._release_candidates[str(choice)] = dict(candidate)
        self._published_release_id = str(choice)
        self.base_schedule = {
            int(a_id): dict(info)
            for a_id, info in dict(candidate.get("schedule", {}) or {}).items()
            if isinstance(info, dict)
        }
        self._protected_baseline = protect_baseline_state(
            protected=True,
            actor=str(self._operator_name),
            reason=f"Published release candidate {choice}",
        )
        self._set_manual_highlight_base(self.base_schedule)
        self._append_audit_log("release_candidate_published", {"name": str(choice)})
        self._refresh_history_view()
        self._save_persistent_history()
        self.set_status(f"Published release candidate {choice}")

    def on_toggle_protected_baseline(self) -> None:
        target = not bool(self._protected_baseline.get("protected", False))
        approval = self._require_approval(
            action="toggle_protected_baseline",
            details={"target": bool(target)},
        )
        if approval is None:
            self.set_status("Protected baseline change canceled")
            return
        self._protected_baseline = protect_baseline_state(
            protected=bool(target),
            actor=str(self._operator_name),
            reason=str(approval.get("reason", "")),
        )
        state = "enabled" if bool(target) else "disabled"
        self._append_audit_log("protected_baseline_toggled", {"state": str(state)})
        self._save_persistent_history()
        self.set_status(f"Protected baseline {state}")

    def on_export_calendar_sync_bundle(self) -> None:
        if not self.current_schedule or self.inst is None:
            self.set_status("No schedule to export")
            return
        folder = QFileDialog.getExistingDirectory(
            self,
            "Export calendar sync bundle",
            "",
        )
        if not folder:
            return
        try:
            export_fn = _window_global("export_calendar_feeds", export_calendar_feeds)
            manifest = export_fn(self.inst, self.current_schedule, folder)
            bundle = build_calendar_sync_bundle(
                manifest,
                base_url=str(self._effective_branding().get("website_url", "")),
            )
            out_path = os.path.join(folder, "calendar_sync_bundle.json")
            write_calendar_sync_bundle(out_path, bundle)
            self._append_audit_log(
                "calendar_sync_bundle_exported",
                {"path": str(out_path), "feeds": int(sum(len(v) for v in dict(manifest.get("feeds", {}) or {}).values()))},
            )
            self.set_status(f"Calendar sync bundle exported to {out_path}")
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Sync export error", str(exc))

    def on_load_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load project",
            "",
            "Project (*.json *.pkl *.db *.sqlite)",
        )
        if not path:
            return

        try:
            self.set_status("Loading project...")
            inst, schedule, _meta = load_legacy_project(path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Load error", str(e))
            self.set_status("Load error")
            return

        self.inst = inst
        self.locked_activities = dict(getattr(inst, "locked_activities", {}) or {})
        self.base_schedule = schedule
        self.current_schedule = {a_id: info.copy() for a_id, info in schedule.items()}
        if isinstance(_meta, dict):
            self._operator_name = str(_meta.get("operator_name", self._operator_name) or self._operator_name)
            self._branches = {
                str(name): dict(branch)
                for name, branch in dict(_meta.get("branches", {}) or {}).items()
                if isinstance(branch, dict)
            }
            active_branch = _meta.get("active_branch_name")
            self._active_branch_name = str(active_branch) if active_branch else None
            self._release_candidates = {
                str(name): dict(candidate)
                for name, candidate in dict(_meta.get("release_candidates", {}) or {}).items()
                if isinstance(candidate, dict)
            }
            published = _meta.get("published_release_id")
            self._published_release_id = str(published) if published else None
            self._protected_baseline = dict(_meta.get("protected_baseline", self._protected_baseline) or {})
            self._workspace_change_log = [
                dict(row)
                for row in list(_meta.get("change_history", []) or [])
                if isinstance(row, dict)
            ][-200:]
            self._import_export_template_path = str(
                _meta.get(
                    "import_export_template_store_path",
                    self._import_export_template_path,
                )
                or self._import_export_template_path
            )
            self._branding_profile = ensure_branding_profile(
                dict(_meta.get("branding_profile", self._branding_profile) or {})
            )
            self._runtime_settings = save_runtime_settings(
                self._runtime_paths["settings"],
                dict(_meta.get("runtime_settings", self._runtime_settings) or {}),
            )
            self._last_import_mapping = {
                str(k): str(v)
                for k, v in dict(_meta.get("last_import_mapping", {}) or {}).items()
            }
            self._last_group_separator = str(_meta.get("last_group_separator", self._last_group_separator) or self._last_group_separator)
        self._set_manual_highlight_base(self.current_schedule)
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        self._load_constraint_controls_from_instance(self.inst)
        self._refresh_product_scenario_from_instance()

        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self._apply_branding_profile()
        self._refresh_history_view()
        self._refresh_history_buttons()
        self.set_status(f"Loaded {path}")
        self._append_audit_log("project_loaded", {"path": str(path)})
        self._save_persistent_history()

    def on_load_product_scenario(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Load {APP_SHORT_NAME} product scenario",
            "",
            "Product Scenario (*.json)",
        )
        if not path:
            return
        try:
            self.set_status("Loading product scenario...")
            scenario = load_product_scenario(path)
            inst = compile_scenario_instance(scenario)
            self.product_scenario = scenario
            self.inst = inst
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(self, "Load error", str(exc))
            self.set_status("Load error")
            return

        self.locked_activities = dict(getattr(inst, "locked_activities", {}) or {})
        self.base_schedule = {}
        self._set_manual_highlight_base({})
        self.current_schedule = {}
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        self._load_constraint_controls_from_instance(self.inst)
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self.set_status(f"Loaded product scenario {path}")
        self._append_audit_log("product_scenario_loaded", {"path": str(path)})
        self._save_persistent_history()

    def on_compare(self):
        if not self.current_schedule:
            self.set_status("No schedule to compare")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Compare with project",
            "",
            "Project (*.json *.pkl)",
        )
        if not path:
            return

        try:
            inst, schedule, _meta = load_legacy_project(path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Compare error", str(e))
            self.set_status("Compare error")
            return

        summary = compare_schedule_sets(self.current_schedule, schedule)
        lines = [
            f"Shared activities: {summary['shared']}",
            f"Missing in other: {len(summary['missing_in_other'])}",
            f"Missing in current: {len(summary['missing_in_base'])}",
            f"Changed time: {summary['changed_time']}",
            f"  - Changed day: {summary['changed_day']}",
            f"  - Changed slot: {summary['changed_slot']}",
            f"Changed room: {summary['changed_room']}",
            f"Changed staff: {summary['changed_staff']}",
        ]
        top_groups = self._top_counts(summary.get("group_move_counts", {}))
        if top_groups:
            labels: list[str] = []
            for g_id, count in top_groups:
                g = self.inst.groups.get(g_id) if self.inst else None
                labels.append(f"{g.name if g else g_id} ({count})")
            lines.append("Top moved groups: " + ", ".join(labels))
        top_staff = self._top_counts(summary.get("staff_move_counts", {}))
        if top_staff:
            labels = []
            for s_id, count in top_staff:
                s = self.inst.staff.get(s_id) if self.inst else None
                labels.append(f"{s.name if s else s_id} ({count})")
            lines.append("Top moved staff: " + ", ".join(labels))
        if summary["missing_in_other"] or summary["missing_in_base"]:
            lines.append("Note: schedules are not based on identical activity sets.")
        if inst.weeks != getattr(self.inst, "weeks", []):
            lines.append("Note: compared scenario has different week set.")
        QMessageBox.information(self, "Schedule comparison", "\n".join(lines))
        # Optional export
        try:
            save = QMessageBox.question(
                self,
                "Save comparison report?",
                "Save a comparison report (JSON/CSV)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if save == QMessageBox.StandardButton.Yes:
                out_path, _ = QFileDialog.getSaveFileName(
                    self,
                    "Save comparison report",
                    "comparison.json",
                    "Report (*.json *.csv)",
                )
                if out_path:
                    write_comparison_report(out_path, summary)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.warning(self, "Report error", str(e))
        self.set_status("Comparison complete")

    def _search_result_rows(self, scope: str, query: str) -> List[List[Any]]:
        rows: List[List[Any]] = []
        needle = str(query or "").strip().lower()
        if self.inst is None:
            return rows

        def _match(*parts: Any) -> bool:
            haystack = " ".join(str(part) for part in parts if part is not None).lower()
            return (not needle) or (needle in haystack)

        include_all = str(scope).lower() == "all"
        if include_all or str(scope).lower() == "activities":
            if self.current_schedule:
                source = self.current_schedule
            else:
                source = {
                    int(a_id): {
                        "week": int(act.week),
                        "day": "-",
                        "slot": 0,
                        "duration": int(act.duration),
                        "room_id": None,
                        "staff_id": int(act.prof_id if act.kind == "LEC" else act.ta_id),
                        "course_id": int(act.course_id),
                        "group_ids": list(act.group_ids),
                        "kind": str(act.kind),
                    }
                    for a_id, act in self.inst.activities.items()
                }
            for a_id, info in source.items():
                title = self._activity_title(int(a_id), source)
                if str(info.get("day")) == "-":
                    detail = f"W{int(info['week'])} unscheduled"
                else:
                    detail = f"W{int(info['week'])} {info['day']} S{int(info['slot']) + 1}"
                if _match(title, detail, info.get("kind"), info.get("course_id")):
                    rows.append(
                        [
                            "Activity",
                            title,
                            detail,
                            {"kind": "activity", "activity_id": int(a_id)},
                        ]
                    )
        if include_all or str(scope).lower() == "staff":
            for s_id, staff in self.inst.staff.items():
                if _match(staff.name, "Professor" if staff.is_prof else "TA", s_id):
                    rows.append(
                        [
                            "Staff",
                            str(staff.name),
                            f"{'Professor' if staff.is_prof else 'TA'} | id {int(s_id)}",
                            {"kind": "staff", "staff_id": int(s_id)},
                        ]
                    )
        if include_all or str(scope).lower() == "rooms":
            for room_id, room in self.inst.rooms.items():
                if _match(room.name, room.campus, room.building, room.floor, room.room_type):
                    detail = f"{room.room_type} | {room.campus}/{room.building}/{room.floor or '-'}"
                    rows.append(
                        [
                            "Room",
                            str(room.name),
                            detail,
                            {"kind": "room", "room_id": int(room_id)},
                        ]
                    )
        if include_all or str(scope).lower() == "conflicts":
            for error in self._collect_conflict_errors():
                if not _match(error):
                    continue
                activity_id = None
                matches = re.findall(r"\bA(\d+)\b", str(error))
                if matches:
                    activity_id = int(matches[0])
                rows.append(
                    [
                        "Conflict",
                        f"A{activity_id}" if activity_id is not None else "-",
                        str(error),
                        {"kind": "conflict", "activity_id": activity_id},
                    ]
                )
        return rows

    def _apply_search_result(self, payload: Dict[str, Any]) -> None:
        kind = str(payload.get("kind", ""))
        if kind in {"activity", "conflict"}:
            activity_id = payload.get("activity_id")
            if activity_id is not None and self._jump_to_activity(int(activity_id)):
                self.set_status(f"Jumped to A{int(activity_id)}")
                return
        if kind == "staff":
            self.view_type_combo.setCurrentText("Staff")
            idx = self.entity_combo.findData(int(payload.get("staff_id", -1)))
            if idx >= 0:
                self.entity_combo.setCurrentIndex(idx)
            self.set_status("Filtered to selected staff member")
            return
        if kind == "room":
            self.view_type_combo.setCurrentText("Room")
            idx = self.entity_combo.findData(int(payload.get("room_id", -1)))
            if idx >= 0:
                self.entity_combo.setCurrentIndex(idx)
            self.set_status("Filtered to selected room")
            return
        self.set_status("No matching jump target")

    def on_run_search(self) -> None:
        if self.inst is None:
            self.set_status("Generate or load an instance first")
            return
        query = str(self.search_edit.text() or "").strip()
        scope = str(self.search_scope_combo.currentText() or "All")
        rows = self._search_result_rows(scope, query)
        dlg = SearchResultsDialog(
            self,
            ["Scope", "Label", "Detail", "__payload__"],
            rows,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        payload = dlg.selected_payload()
        if payload:
            self._apply_search_result(payload)

    def on_load_instance(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load instance",
            "",
            "Instance (*.json *.pkl)",
        )
        if not path:
            return

        try:
            self.set_status("Loading instance...")
            inst = read_instance(path)
            normalize_instance_for_spec(inst)
            stamp_instance_time(inst, DEFAULT_DAY_START, DEFAULT_SLOT_MINUTES, DEFAULT_BREAK_MINUTES)
            validate_instance_against_spec(inst)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Load error", str(e))
            self.set_status("Load error")
            return

        self.inst = inst
        self.locked_activities = dict(getattr(inst, "locked_activities", {}) or {})
        self.base_schedule = {}
        self._set_manual_highlight_base({})
        self.current_schedule = {}
        self.held_activity_id = None
        self._bump_schedule_revision()
        self._reset_history()
        self._load_constraint_controls_from_instance(self.inst)
        self._refresh_product_scenario_from_instance()
        self.populate_weeks()
        self.update_entities()
        self.update_table()
        self.update_quality_summary()
        self.set_status(f"Loaded instance {path}")
        self._append_audit_log("instance_loaded", {"path": str(path)})
        self._save_persistent_history()

    def on_load_schedule(self):
        if self.inst is None:
            self.set_status("Load instance first")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load schedule (CSV)",
            "",
            "CSV files (*.csv)",
        )
        if not path:
            return

        try:
            self.set_status("Loading schedule...")
            schedule = read_schedule_csv(path)
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, "Load error", str(e))
            self.set_status("Load error")
            return
        self._load_validated_schedule(schedule, source=str(path))

    # ----- table rendering -----

    def compute_group_penalties(self, schedule: Dict[int, Dict[str, Any]]) -> Dict[int, int]:
        inst = self.inst
        if inst is None:
            return {}

        days = inst.days
        weeks = inst.weeks
        S = inst.slots_per_day

        weights = {
            "stud_free_days": 10,
            "stud_free_mf": 5,
            "stud_gaps": 5,
            "active_days": 5,
            "late_start": 3,
            "thin_day": 3,
            "stability": 1,
            "single_slot": 6,
            "same_kind_week": 3,
        }
        overrides = getattr(inst, "soft_weights", None)
        if isinstance(overrides, dict):
            for k, v in overrides.items():
                if k in weights:
                    try:
                        weights[k] = int(v)
                    except Exception:
                        pass

        W_STUD_FREE_DAYS = weights["stud_free_days"]
        W_STUD_FREE_MF = weights["stud_free_mf"]
        W_STUD_GAPS = weights["stud_gaps"]
        W_ACTIVE_DAYS = weights["active_days"]
        W_LATE_START = weights["late_start"]
        W_THIN_DAY = weights["thin_day"]
        W_STABILITY = weights["stability"]
        W_SINGLE_SLOT = weights["single_slot"]
        W_SAME_KIND_WEEK = weights["same_kind_week"]

        group_occ: Dict[Tuple[int, int, str, int], int] = {}
        for g_id in inst.groups.keys():
            for w in weeks:
                for d in days:
                    for s in range(S):
                        group_occ[g_id, w, d, s] = 0

        for a_id, info in schedule.items():
            w = info["week"]
            d = info["day"]
            s0 = info["slot"]
            dur = info["duration"]
            for ds in range(dur):
                s = s0 + ds
                if s < 0 or s >= S:
                    continue
                for g_id in info["group_ids"]:
                    group_occ[g_id, w, d, s] = 1

        day_active: Dict[Tuple[int, int, str], int] = {}
        for g_id in inst.groups.keys():
            for w in weeks:
                for d in days:
                    occs = [group_occ[g_id, w, d, s] for s in range(S)]
                    day_active[g_id, w, d] = 1 if any(occs) else 0

        penalties: Dict[int, int] = {g_id: 0 for g_id in inst.groups.keys()}

        workdays = [d for d in days if d in {"MON", "TUE", "WED", "THU", "FRI"}]

        for g_id, g in inst.groups.items():
            pen = 0

            for w in weeks:
                free_days = sum(1 - day_active[g_id, w, d] for d in days)
                if free_days < g.preferred_free_days:
                    pen += W_STUD_FREE_DAYS * (g.preferred_free_days - free_days)

                free_mf = sum(1 - day_active[g_id, w, d] for d in workdays)
                if free_mf < g.preferred_free_days:
                    pen += W_STUD_FREE_MF * (g.preferred_free_days - free_mf)

                for d in days:
                    occ = [group_occ[g_id, w, d, s] for s in range(S)]
                    blocks = 0
                    prev = 0
                    load = 0
                    first_slot = None
                    for idx, v in enumerate(occ):
                        if v == 1 and prev == 0:
                            blocks += 1
                        if v == 1:
                            load += 1
                            if first_slot is None:
                                first_slot = idx
                        prev = v
                    if blocks > 1:
                        pen += W_STUD_GAPS * (blocks - 1)
                    if load == 1:
                        pen += W_SINGLE_SLOT
                    if load == 2:
                        pen += W_THIN_DAY
                    if first_slot is not None and first_slot >= 2:
                        pen += W_LATE_START

                active_days = sum(day_active[g_id, w, d] for d in days)
                if active_days > 3:
                    pen += W_ACTIVE_DAYS * (active_days - 3)

                same_kind_counts: Dict[Tuple[int, str], int] = {}
                for info in schedule.values():
                    if int(info.get("week")) != int(w):
                        continue
                    if int(g_id) not in set(int(x) for x in info.get("group_ids", [])):
                        continue
                    kind = str(info.get("kind", ""))
                    if kind not in ("LEC", "TUT"):
                        continue
                    key = (int(info.get("course_id", -1)), kind)
                    same_kind_counts[key] = int(same_kind_counts.get(key, 0)) + 1
                for cnt in same_kind_counts.values():
                    if int(cnt) > 1:
                        pen += int(W_SAME_KIND_WEEK) * int(cnt - 1)

            for wi in range(1, len(weeks)):
                w_prev = weeks[wi - 1]
                w_curr = weeks[wi]
                for d in days:
                    if day_active[g_id, w_prev, d] != day_active[g_id, w_curr, d]:
                        pen += W_STABILITY

            penalties[g_id] = pen

        return penalties

    def classify_group_quality(self, pen: int) -> str:
        if pen <= 10:
            return "optimal"
        if pen <= 80:
            return "near-optimal"
        if pen <= 220:
            return "decent"
        return "bad"

    def update_quality_summary(self):
        if self.inst is None or not self.current_schedule:
            self.quality_label.setText("")
            self._update_fairness_dashboard()
            self._update_diagnostics_dashboard()
            return

        hard_conflicts = 0
        global_penalty = None
        breakdown: Dict[str, int] = {}
        sla_summary: Dict[str, Any] = {}
        try:
            breakdown = compute_penalty_breakdown(self.inst, self.current_schedule)
            global_penalty = int(breakdown.get("total", 0))
        except Exception:
            global_penalty = None
            breakdown = {}
        try:
            hard_conflicts = len(self._collect_conflict_errors())
        except Exception:
            hard_conflicts = 0
        try:
            sla_summary = evaluate_schedule_sla(
                self.inst,
                self.current_schedule,
                hard_conflicts=int(hard_conflicts),
            )
        except Exception:
            sla_summary = {}

        penalties = self.compute_group_penalties(self.current_schedule)
        if not penalties:
            self.quality_label.setText("")
            self._update_diagnostics_dashboard()
            return

        header_parts: List[str] = []
        if global_penalty is not None:
            header_parts.append(f"Global soft penalty: {global_penalty}")
        header_parts.append(f"Hard conflicts: {hard_conflicts}")
        header_parts.append(
            f"Profile: {self.objective_profile_combo.currentText()}"
        )
        cp_bound_summary = self._cp_bound_summary_from_meta()
        if cp_bound_summary:
            header_parts.append(cp_bound_summary)
        if isinstance(sla_summary, dict) and sla_summary:
            if bool(sla_summary.get("passed", True)):
                header_parts.append("SLA: pass")
            else:
                violations = ", ".join(str(v) for v in (sla_summary.get("violations") or []))
                header_parts.append(f"SLA: fail ({violations or 'thresholds'})")
        if self.held_activity_id is not None:
            header_parts.append(f"Held: A{self.held_activity_id}")

        detail_parts: List[str] = []
        if breakdown:
            top_terms = [
                (key, int(value))
                for key, value in breakdown.items()
                if key != "total" and int(value) > 0
            ]
            top_terms.sort(key=lambda item: item[1], reverse=True)
            if top_terms:
                detail_parts.append(
                    "Top penalty drivers: "
                    + " | ".join(f"{key}={value}" for key, value in top_terms[:4])
                )
        if self.base_schedule and self.current_schedule != self.base_schedule:
            try:
                detail_parts.append(
                    explain_solution_ranking(
                        self.inst,
                        self.base_schedule,
                        self.current_schedule,
                        base_label="base",
                        candidate_label="current",
                    )
                )
            except Exception:
                pass

        parts: List[str] = []
        for g_id in sorted(self.inst.groups.keys()):
            pen = penalties.get(g_id, 0)
            g = self.inst.groups[g_id]
            status = self.classify_group_quality(pen)
            parts.append(f"{g.name}: {pen} ({status})")

        lines = [" | ".join(header_parts)]
        lines.extend(detail_parts)
        lines.append("Group quality:")
        lines.append(" | ".join(parts))
        text = "\n".join(line for line in lines if line)
        self.quality_label.setText(text)
        self._update_fairness_dashboard()
        self._update_diagnostics_dashboard()

    def _update_fairness_dashboard(self) -> None:
        if not hasattr(self, "fairness_group_table") or not hasattr(
            self, "fairness_staff_table"
        ):
            return
        if self.inst is None or not self.current_schedule:
            self.fairness_group_model.set_table(self.fairness_group_model._headers, [])
            self.fairness_staff_model.set_table(self.fairness_staff_model._headers, [])
            self.fairness_summary_label.setText(
                "Generate/solve to view fairness dashboard."
            )
            return
        try:
            dashboard = compute_fairness_dashboard(self.inst, self.current_schedule)
        except Exception as exc:
            self.fairness_summary_label.setText(
                f"Fairness dashboard unavailable: {exc}"
            )
            return

        group_rows = list(dashboard.get("groups", []))
        staff_rows = list(dashboard.get("staff", []))
        self.fairness_group_model.set_table(
            self.fairness_group_model._headers,
            [
                [
                    str(row.get("name", "")),
                    int(row.get("total_slots", 0)),
                    int(row.get("active_days", 0)),
                    int(row.get("single_days", 0)),
                    int(row.get("gap_slots", 0)),
                    int(row.get("late_events", 0)),
                    float(row.get("avg_weekly_load", 0.0)),
                    float(row.get("fairness_score", 0.0)),
                ]
                for row in group_rows
            ],
        )
        self.fairness_staff_model.set_table(
            self.fairness_staff_model._headers,
            [
                [
                    str(row.get("name", "")),
                    str(row.get("role", "")),
                    int(row.get("total_slots", 0)),
                    int(row.get("active_days", 0)),
                    int(row.get("single_days", 0)),
                    int(row.get("gap_slots", 0)),
                    int(row.get("late_events", 0)),
                    float(row.get("avg_weekly_load", 0.0)),
                    float(row.get("fairness_score", 0.0)),
                ]
                for row in staff_rows
            ],
        )

        summary = dashboard.get("summary", {})
        g_sum = summary.get("groups", {}) if isinstance(summary, dict) else {}
        s_sum = summary.get("staff", {}) if isinstance(summary, dict) else {}
        self.fairness_summary_label.setText(
            "Fairness summary | "
            f"Groups mean score: {float(g_sum.get('mean_fairness_score', 0.0)):.2f} | "
            f"Staff mean score: {float(s_sum.get('mean_fairness_score', 0.0)):.2f}"
        )

    # ----- manual edit -----
