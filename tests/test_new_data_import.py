from __future__ import annotations

from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import pytest

from services.teaching_load_import_service import load_teaching_load_assignments
from services.timetable_import_service import import_timetable_csv


ROOT = Path(__file__).resolve().parent.parent
WORKBOOK = ROOT / "data" / "new" / "Mail WS25 Berlin Teaching load_14.9.2025.xlsx"
QUIZ_ARCHIVE = ROOT / "data" / "new" / "Fw_ Berlin W25 Quizzes Calendars .zip"


def test_new_teaching_load_workbook_extracts_named_course_assignments():
    if not WORKBOOK.exists():
        pytest.skip("data/new teaching-load workbook is not present")

    catalog = load_teaching_load_assignments(WORKBOOK)

    assert len(catalog["sheets"]) == 9
    assert len(catalog["courses"]) >= 150
    assert sum(bool(row["lecturers"]) for row in catalog["courses"].values()) >= 120
    assert sum(bool(row["tas"]) for row in catalog["courses"].values()) >= 120
    assert catalog["courses"]["MATHB201"]["lecturers"] == ["Arian Berdellima"]
    assert catalog["courses"]["MATHB201"]["tas"] == ["Adel Fouad"]
    assert "Turker Ince" in catalog["courses"]["CSENB401"]["lecturers"]


def test_new_quiz_calendar_archive_contains_expected_pdf_corpus():
    if not QUIZ_ARCHIVE.exists():
        pytest.skip("data/new quiz archive is not present")
    with ZipFile(QUIZ_ARCHIVE) as archive:
        pdfs = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
    assert len(pdfs) == 12
    assert any("BINF 5th" in name for name in pdfs)
    assert any("MCTR 9th" in name for name in pdfs)


def test_timetable_import_uses_exact_teaching_load_staff(tmp_path: Path):
    if not WORKBOOK.exists():
        pytest.skip("data/new teaching-load workbook is not present")
    csv_path = tmp_path / "matched.csv"
    csv_path.write_text(
        "week,day,slot,course,major,room,kind\n"
        "1,Monday,1,MATH B201 Mathematics III,G1,L1,LEC\n"
        "2,Tuesday,1,MATH B201 Mathematics III,G1,T1,TUT\n"
        "1,Wednesday,1,MATH B401 Mathematics V,G2,L2,LEC\n",
        encoding="utf-8",
    )

    inst, _schedule, meta = import_timetable_csv(
        csv_path,
        teaching_load_path=WORKBOOK,
    )

    assert meta["teaching_load_matches"] == 2
    arian = [staff for staff in inst.staff.values() if staff.name == "Arian Berdellima"]
    adel = [staff for staff in inst.staff.values() if staff.name == "Adel Fouad"]
    assert len(arian) == 1
    assert len(adel) == 1
    assert len(arian[0].can_teach_courses) == 2
    assert adel[0].is_prof is False


def test_unmatched_catalog_balances_three_to_four_courses_per_staff(tmp_path: Path):
    csv_path = tmp_path / "fallback.csv"
    rows = ["week,day,slot,course,major,room,kind"]
    for index in range(14):
        rows.append(f"1,Monday,1,C{index + 1:03d} Course {index + 1},G1,R{index + 1},LEC")
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    inst, _schedule, meta = import_timetable_csv(csv_path)

    assert meta["synthetic_staff_pool_size_per_role"] == 4
    role_loads = Counter()
    for staff in inst.staff.values():
        role_loads["prof" if staff.is_prof else "ta"] += 1
        assert 3 <= len(staff.can_teach_courses) <= 4
    assert role_loads == {"prof": 4, "ta": 4}
