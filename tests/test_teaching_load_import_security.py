from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from services.teaching_load_import_service import load_teaching_load_assignments
from services import teaching_load_import_service


WORKBOOK_XML = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Load" sheetId="1" r:id="rId1"/></sheets>
</workbook>
"""

WORKBOOK_RELS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
   Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
   Target="worksheets/sheet1.xml"/>
</Relationships>
"""


def _inline_cell(reference: str, value: str) -> str:
    return f'<c r="{reference}" t="inlineStr"><is><t>{value}</t></is></c>'


def _safe_sheet_xml(*, extra_cell: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1">{_inline_cell("A1", "Course code")}{_inline_cell("B1", "Lecturer")}{extra_cell}</row>
    <row r="2">{_inline_cell("A2", "CS101")}{_inline_cell("B2", "Dr. Alice")}</row>
  </sheetData>
</worksheet>
"""


def _write_workbook(
    path: Path,
    *,
    sheet_xml: str,
    shared_strings_xml: str | None = None,
) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", WORKBOOK_XML)
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS_XML)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        if shared_strings_xml is not None:
            archive.writestr("xl/sharedStrings.xml", shared_strings_xml)


def test_bounded_xlsx_parser_accepts_normal_teaching_load(tmp_path: Path) -> None:
    path = tmp_path / "teaching-load.xlsx"
    _write_workbook(path, sheet_xml=_safe_sheet_xml())

    result = load_teaching_load_assignments(path)

    assert result["sheets"] == ["Load"]
    assert result["courses"]["CS101"]["lecturers"] == ["Alice"]


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("ZZZZZZZZ1", "Invalid Excel cell reference"),
        ("XFE1", "exceeds XFD bounds"),
        ("XFD1", "512-column import limit"),
    ],
)
def test_bounded_xlsx_parser_rejects_adversarial_sparse_columns(
    tmp_path: Path,
    reference: str,
    message: str,
) -> None:
    path = tmp_path / f"sparse-{reference}.xlsx"
    _write_workbook(
        path,
        sheet_xml=_safe_sheet_xml(extra_cell=_inline_cell(reference, "boom")),
    )

    with pytest.raises(ValueError, match=message):
        load_teaching_load_assignments(path)


def test_bounded_xlsx_parser_rejects_high_ratio_member(tmp_path: Path) -> None:
    path = tmp_path / "compressed-bomb.xlsx"
    repeated = "A" * (1024 * 1024)
    shared = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<si><t>{repeated}</t></si></sst>"
    )
    _write_workbook(path, sheet_xml=_safe_sheet_xml(), shared_strings_xml=shared)

    with pytest.raises(ValueError, match="compression ratio is unsafe"):
        load_teaching_load_assignments(path)


def test_bounded_xlsx_parser_rejects_xml_entity_declarations(tmp_path: Path) -> None:
    path = tmp_path / "entity.xlsx"
    sheet = _safe_sheet_xml().replace(
        '<worksheet xmlns=',
        '<!DOCTYPE worksheet [<!ENTITY x "expanded">]><worksheet xmlns=',
        1,
    )
    _write_workbook(path, sheet_xml=sheet)

    with pytest.raises(ValueError, match="XML declarations are not allowed"):
        load_teaching_load_assignments(path)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_bounded_xlsx_parser_rejects_wide_encoded_entity_declarations(
    tmp_path: Path,
    encoding: str,
) -> None:
    path = tmp_path / f"entity-{encoding}.xlsx"
    sheet = _safe_sheet_xml().replace(
        '<worksheet xmlns=',
        '<!DOCTYPE worksheet [<!ENTITY x "Dr. Mallory">]><worksheet xmlns=',
        1,
    )
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", WORKBOOK_XML)
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS_XML)
        archive.writestr("xl/worksheets/sheet1.xml", sheet.encode(encoding))

    with pytest.raises(ValueError, match="UTF-8-compatible encoding"):
        load_teaching_load_assignments(path)


def test_xlsx_file_size_is_rejected_before_zipfile_construction(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "oversized.xlsx"
    with path.open("wb") as stream:
        stream.seek(teaching_load_import_service._MAX_XLSX_COMPRESSED_BYTES)
        stream.write(b"x")

    opened = False

    def _unexpected_zipfile(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("ZipFile must not inspect an oversized archive")

    monkeypatch.setattr(teaching_load_import_service, "ZipFile", _unexpected_zipfile)
    with pytest.raises(ValueError, match="compressed file exceeds"):
        load_teaching_load_assignments(path)
    assert opened is False


def test_xlsx_entry_count_is_rejected_before_zipfile_construction(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "many-members.xlsx"
    with ZipFile(path, "w") as archive:
        for index in range(teaching_load_import_service._MAX_XLSX_MEMBERS + 1):
            archive.writestr(f"empty/{index}", b"")

    opened = False

    def _unexpected_zipfile(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("ZipFile must not allocate the central directory")

    monkeypatch.setattr(teaching_load_import_service, "ZipFile", _unexpected_zipfile)
    with pytest.raises(ValueError, match="too many archive members"):
        load_teaching_load_assignments(path)
    assert opened is False
