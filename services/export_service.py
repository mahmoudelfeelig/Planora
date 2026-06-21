from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from services.branding_service import ensure_branding_profile
from services.diagnostics_service import (
    build_stakeholder_quality_report,
    compute_entity_heatmaps,
    write_stakeholder_quality_report,
)
from utils.exporter import (
    export_calendar_feeds,
    export_groups_ics_per_id,
    export_groups_pdf,
    export_group_schedules_to_docx,
    export_rooms_ics_per_id,
    export_schedule_to_csv,
    export_staff_ics_per_id,
    export_summary_reports,
    write_heatmap_reports,
)


def export_docx(
    inst,
    schedule: Dict[int, Dict[str, Any]],
    path: str | Path,
    *,
    branding: Dict[str, Any] | None = None,
) -> str:
    export_group_schedules_to_docx(inst, schedule, str(path), branding=branding)
    return str(path)


def export_pdf(
    inst,
    schedule: Dict[int, Dict[str, Any]],
    path: str | Path,
    *,
    branding: Dict[str, Any] | None = None,
) -> str:
    export_groups_pdf(inst, schedule, path, branding=branding)
    return str(path)


def export_reports(
    inst,
    schedule: Dict[int, Dict[str, Any]],
    out_dir: str | Path,
    *,
    branding: Dict[str, Any] | None = None,
    baseline_schedule: Dict[int, Dict[str, Any]] | None = None,
) -> str:
    profile = ensure_branding_profile(branding)
    export_summary_reports(inst, schedule, out_dir, branding=profile)
    report = build_stakeholder_quality_report(
        inst,
        schedule,
        branding=profile,
        baseline_schedule=baseline_schedule,
    )
    write_stakeholder_quality_report(out_dir, report)
    write_heatmap_reports(out_dir, compute_entity_heatmaps(inst, schedule))
    return str(out_dir)


def export_csv(inst, schedule: Dict[int, Dict[str, Any]], path: str | Path) -> str:
    export_schedule_to_csv(inst, schedule, str(path))
    return str(path)


def export_ics(inst, schedule: Dict[int, Dict[str, Any]], out_dir: str | Path) -> str:
    export_groups_ics_per_id(inst, schedule, str(out_dir))
    export_staff_ics_per_id(inst, schedule, str(out_dir))
    export_rooms_ics_per_id(inst, schedule, str(out_dir))
    return str(out_dir)


def export_bundle(
    inst,
    schedule: Dict[int, Dict[str, Any]],
    out_dir: str | Path,
    *,
    branding: Dict[str, Any] | None = None,
    baseline_schedule: Dict[int, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    docx_path = root / "schedule.docx"
    csv_path = root / "schedule.csv"
    pdf_path = root / "groups.pdf"
    reports_dir = root / "reports"
    feeds_dir = root / "feeds"
    ics_dir = root / "ics"

    export_group_schedules_to_docx(inst, schedule, str(docx_path), branding=branding)
    export_schedule_to_csv(inst, schedule, str(csv_path))
    export_groups_pdf(inst, schedule, pdf_path, branding=branding)
    export_reports(
        inst,
        schedule,
        reports_dir,
        branding=branding,
        baseline_schedule=baseline_schedule,
    )
    export_groups_ics_per_id(inst, schedule, str(ics_dir))
    export_staff_ics_per_id(inst, schedule, str(ics_dir))
    export_rooms_ics_per_id(inst, schedule, str(ics_dir))
    manifest = export_calendar_feeds(inst, schedule, str(feeds_dir))
    return {
        "docx": str(docx_path),
        "csv": str(csv_path),
        "pdf": str(pdf_path),
        "reports_dir": str(reports_dir),
        "ics_dir": str(ics_dir),
        "feeds_manifest": manifest,
    }
