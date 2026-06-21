from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List
from zipfile import ZipFile


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def normalize_course_code(value: Any) -> str:
    text = _clean(value).upper()
    parts = re.findall(r"[A-Z]{2,}\s*[A-Z]?\d{2,}|[A-Z]{1,8}\s+[A-Z]\d{2,}", text)
    code = parts[0] if parts else text.splitlines()[0] if text else ""
    return re.sub(r"[^A-Z0-9]", "", code)


def normalize_course_name(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _clean(value).upper())


def normalize_staff_name(value: Any) -> str:
    text = _clean(value)
    text = re.sub(r"\([^)]*(?:FT|PT|CAIRO|TURKEY|50%)[^)]*\)", "", text, flags=re.I)
    text = re.sub(r"^(?:PROF\.?|DR\.?|MED\.)\s+", "", text, flags=re.I)
    return _clean(text).strip(" ,;")


def _column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", str(cell_ref).upper())
    value = 0
    for char in letters.group(0) if letters else "A":
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value - 1


def _xlsx_sheets(path: str | Path) -> Iterable[tuple[str, List[List[str]]]]:
    with ZipFile(Path(path)) as archive:
        ns = {"m": _MAIN_NS, "r": _REL_NS}
        shared: List[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", ns):
                shared.append("".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t")))

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {node.attrib["Id"]: node.attrib["Target"] for node in relationships}
        sheets_node = workbook.find("m:sheets", ns)
        for sheet in list(sheets_node) if sheets_node is not None else []:
            name = str(sheet.attrib.get("name", "Sheet"))
            rel_id = sheet.attrib.get(f"{{{_REL_NS}}}id", "")
            target = targets.get(rel_id, "")
            member = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
            if member not in archive.namelist():
                continue
            root = ET.fromstring(archive.read(member))
            rows: List[List[str]] = []
            for row in root.findall(".//m:sheetData/m:row", ns):
                values: Dict[int, str] = {}
                for cell in row.findall("m:c", ns):
                    index = _column_index(cell.attrib.get("r", "A1"))
                    cell_type = cell.attrib.get("t", "")
                    raw = cell.find("m:v", ns)
                    value = "" if raw is None else str(raw.text or "")
                    if cell_type == "s" and value:
                        value = shared[int(value)]
                    elif cell_type == "inlineStr":
                        value = "".join(
                            node.text or "" for node in cell.iter(f"{{{_MAIN_NS}}}t")
                        )
                    values[index] = _clean(value)
                width = max(values.keys(), default=-1) + 1
                rows.append([values.get(index, "") for index in range(width)])
            yield name, rows


def _header_index(rows: List[List[str]]) -> int | None:
    for index, row in enumerate(rows[:10]):
        joined = " ".join(_clean(value).lower() for value in row)
        if "course" in joined and ("lecturer" in joined or "teacher" in joined):
            return index
    return None


def _find_column(headers: List[str], patterns: Iterable[str]) -> int | None:
    for pattern in patterns:
        for index, header in enumerate(headers):
            if pattern in _clean(header).lower():
                return index
    return None


def _split_staff_names(value: Any) -> List[str]:
    text = _clean(value)
    if not text or "@" in text or text.lower() in {"x", "nn", "no lecturer needed"}:
        return []
    parts = re.split(r"\s*(?:,|;|\band\b|\n)\s*", text, flags=re.I)
    names: List[str] = []
    for part in parts:
        name = normalize_staff_name(part)
        if not name or name.lower() in {"admin", "total"} or re.fullmatch(r"[\d.]+", name):
            continue
        names.append(name)
    return list(dict.fromkeys(names))


def load_teaching_load_assignments(path: str | Path) -> Dict[str, Any]:
    courses: Dict[str, Dict[str, Any]] = {}
    sheets: List[str] = []
    for sheet_name, rows in _xlsx_sheets(path):
        sheets.append(sheet_name)
        header_row = _header_index(rows)
        if header_row is None:
            continue
        headers = rows[header_row]
        code_columns = [
            index
            for index, header in enumerate(headers)
            if "code" in _clean(header).lower()
            and "mail" not in _clean(header).lower()
        ]
        if not code_columns:
            continue
        berlin_column = _find_column(headers, ("berlin code", "code berlin"))
        name_column = _find_column(headers, ("course name",))
        lecturer_column = _find_column(headers, ("lecturer", "teacher"))
        load_column = _find_column(headers, ("load in", "hours count", "course hours"))
        explicit_ta_column = _find_column(headers, ("ta", "assistant"))
        active_key = ""
        for row in rows[header_row + 1 :]:
            def cell(column: int | None) -> str:
                return row[column] if column is not None and column < len(row) else ""

            raw_codes = [cell(index) for index in code_columns]
            preferred_code = cell(berlin_column)
            candidates = [preferred_code, *raw_codes]
            code = next(
                (
                    normalize_course_code(candidate)
                    for candidate in candidates
                    if normalize_course_code(candidate) not in {"", "X"}
                ),
                "",
            )
            if code:
                active_key = code
                courses.setdefault(
                    active_key,
                    {
                        "course_code": code,
                        "course_name": cell(name_column),
                        "lecturers": [],
                        "tas": [],
                        "sheets": [],
                    },
                )
            if not active_key or active_key not in courses:
                continue
            record = courses[active_key]
            if sheet_name not in record["sheets"]:
                record["sheets"].append(sheet_name)
            if cell(name_column) and not record.get("course_name"):
                record["course_name"] = cell(name_column)

            lecturer_names = _split_staff_names(cell(lecturer_column))
            if code:
                record["lecturers"].extend(lecturer_names)
            elif lecturer_names:
                if any(token in cell(lecturer_column).lower() for token in ("lecturer", "prof", "dr.")):
                    record["lecturers"].extend(lecturer_names)
                else:
                    record["tas"].extend(lecturer_names)

            ta_values: List[str] = []
            if explicit_ta_column is not None:
                ta_values.append(cell(explicit_ta_column))
            elif lecturer_column is not None:
                end = load_column if load_column is not None else len(row)
                for index in range(lecturer_column + 1, min(end, len(row))):
                    value = cell(index)
                    if value and "@" not in value and not re.fullmatch(r"[\d.]+", value):
                        ta_values.append(value)
            for value in ta_values:
                record["tas"].extend(_split_staff_names(value))

    by_name: Dict[str, str] = {}
    for code, record in courses.items():
        record["lecturers"] = list(dict.fromkeys(record["lecturers"]))
        record["tas"] = list(dict.fromkeys(record["tas"]))
        normalized_name = normalize_course_name(record.get("course_name", ""))
        if normalized_name:
            by_name[normalized_name] = code
    return {
        "source_path": str(path),
        "sheets": sheets,
        "courses": courses,
        "course_name_index": by_name,
    }


def match_teaching_assignment(catalog: Dict[str, Any], course_text: str) -> Dict[str, Any] | None:
    courses = dict(catalog.get("courses") or {})
    code = normalize_course_code(course_text)
    if code in courses:
        return dict(courses[code])
    name_key = normalize_course_name(course_text)
    indexed_code = dict(catalog.get("course_name_index") or {}).get(name_key)
    if indexed_code in courses:
        return dict(courses[indexed_code])
    return None


__all__ = [
    "load_teaching_load_assignments",
    "match_teaching_assignment",
    "normalize_course_code",
    "normalize_staff_name",
]
