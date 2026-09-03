from __future__ import annotations

import re
import posixpath
import struct
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Dict, Iterable, List
from zipfile import BadZipFile, ZipFile, ZipInfo


_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_MAX_XLSX_COMPRESSED_BYTES = 64 * 1024 * 1024
_MAX_XLSX_MEMBERS = 2_048
_MAX_XLSX_MEMBER_BYTES = 32 * 1024 * 1024
_MAX_XLSX_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_XLSX_COMPRESSION_RATIO = 200.0
_MAX_XML_ELEMENTS = 2_000_000
_MAX_XML_TEXT_BYTES = 32 * 1024 * 1024
_MAX_METADATA_XML_BYTES = 2 * 1024 * 1024
_MAX_METADATA_XML_ELEMENTS = 20_000
_MAX_METADATA_XML_TEXT_BYTES = 2 * 1024 * 1024
_MAX_SHARED_STRINGS = 200_000
_MAX_SHEETS = 128
_MAX_ROWS_PER_SHEET = 50_000
_MAX_CELLS_PER_SHEET = 1_000_000
_MAX_IMPORT_COLUMNS = 512
_MAX_CELL_TEXT_BYTES = 64 * 1024
_EXCEL_MAX_COLUMN_INDEX = 16_383  # XFD, zero based.
_EXCEL_MAX_ROW = 1_048_576
_XML_FORBIDDEN_MARKERS = (b"<!DOCTYPE", b"<!ENTITY")
_ZIP_EOCD_SIGNATURE = b"PK\x05\x06"


class _BoundedXmlReader:
    def __init__(self, stream: BinaryIO, *, byte_limit: int, member: str):
        self._stream = stream
        self._byte_limit = int(byte_limit)
        self._member = str(member)
        self._read = 0
        self._tail = b""

    def read(self, size: int = -1) -> bytes:
        remaining = self._byte_limit - self._read
        if remaining < 0:
            raise ValueError(f"XLSX member exceeds byte limit: {self._member}")
        request = remaining + 1 if size is None or int(size) < 0 else min(int(size), remaining + 1)
        data = self._stream.read(request)
        self._read += len(data)
        if self._read > self._byte_limit:
            raise ValueError(f"XLSX member exceeds byte limit: {self._member}")
        if b"\x00" in data:
            raise ValueError(
                f"XLSX XML must use UTF-8-compatible encoding: {self._member}"
            )
        scanned = (self._tail + data).upper()
        if any(marker in scanned for marker in _XML_FORBIDDEN_MARKERS):
            raise ValueError(f"XLSX XML declarations are not allowed: {self._member}")
        self._tail = scanned[-32:]
        return data


def _safe_member_name(name: str) -> str:
    normalized = str(name).replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.startswith("/") or ".." in path.parts:
        raise ValueError(f"Unsafe XLSX member path: {name}")
    return normalized


def _preflight_zip_container(path: Path) -> None:
    """Reject oversized or pathological ZIP containers before ZipFile allocates."""

    try:
        compressed_size = int(path.stat().st_size)
    except OSError as exc:
        raise ValueError(f"Unable to inspect XLSX file: {path}") from exc
    if compressed_size > _MAX_XLSX_COMPRESSED_BYTES:
        raise ValueError("XLSX compressed file exceeds the configured size limit")
    if compressed_size < 22:
        raise ValueError("Invalid XLSX ZIP container")

    tail_size = min(compressed_size, 22 + 65_535)
    try:
        with path.open("rb") as stream:
            stream.seek(compressed_size - tail_size)
            tail = stream.read(tail_size)
    except OSError as exc:
        raise ValueError(f"Unable to inspect XLSX file: {path}") from exc

    search_end = len(tail)
    eocd_index = -1
    while search_end >= 0:
        candidate = tail.rfind(_ZIP_EOCD_SIGNATURE, 0, search_end)
        if candidate < 0:
            break
        if candidate + 22 <= len(tail):
            comment_length = struct.unpack_from("<H", tail, candidate + 20)[0]
            if candidate + 22 + int(comment_length) == len(tail):
                eocd_index = candidate
                break
        search_end = candidate
    if eocd_index < 0:
        raise ValueError("Invalid XLSX ZIP end-of-central-directory record")

    (
        _signature,
        disk_number,
        directory_disk,
        entries_on_disk,
        total_entries,
        directory_size,
        directory_offset,
        _comment_length,
    ) = struct.unpack_from("<4s4H2LH", tail, eocd_index)
    if disk_number != 0 or directory_disk != 0 or entries_on_disk != total_entries:
        raise ValueError("Multi-disk XLSX archives are not supported")
    if total_entries == 0xFFFF or directory_size == 0xFFFFFFFF or directory_offset == 0xFFFFFFFF:
        raise ValueError("ZIP64 XLSX archives are not supported")
    if int(total_entries) > _MAX_XLSX_MEMBERS:
        raise ValueError("XLSX contains too many archive members")
    eocd_absolute = compressed_size - tail_size + eocd_index
    if int(directory_offset) + int(directory_size) > eocd_absolute:
        raise ValueError("Invalid XLSX ZIP central directory bounds")


def _preflight_archive(archive: ZipFile) -> Dict[str, ZipInfo]:
    infos = archive.infolist()
    if len(infos) > _MAX_XLSX_MEMBERS:
        raise ValueError("XLSX contains too many archive members")
    members: Dict[str, ZipInfo] = {}
    total_bytes = 0
    for info in infos:
        member = _safe_member_name(info.filename)
        if member in members:
            raise ValueError(f"XLSX contains a duplicate member: {member}")
        if info.flag_bits & 0x1:
            raise ValueError(f"Encrypted XLSX members are not supported: {member}")
        if int(info.file_size) > _MAX_XLSX_MEMBER_BYTES:
            raise ValueError(f"XLSX member exceeds the configured size limit: {member}")
        total_bytes += int(info.file_size)
        if total_bytes > _MAX_XLSX_TOTAL_BYTES:
            raise ValueError("XLSX uncompressed data exceeds the configured total limit")
        if int(info.file_size) >= 4_096:
            compressed = max(1, int(info.compress_size))
            if float(info.file_size) / float(compressed) > _MAX_XLSX_COMPRESSION_RATIO:
                raise ValueError(f"XLSX member compression ratio is unsafe: {member}")
        members[member] = info
    return members


def _preflight_xml_structure(
    archive: ZipFile,
    info: ZipInfo,
    *,
    byte_limit: int,
    element_limit: int,
    text_limit: int,
) -> None:
    if int(info.file_size) > int(byte_limit):
        raise ValueError(f"XLSX XML member exceeds the metadata limit: {info.filename}")
    elements = 0
    text_bytes = 0
    try:
        with archive.open(info, "r") as stream:
            reader = _BoundedXmlReader(
                stream,
                byte_limit=min(int(info.file_size), int(byte_limit)),
                member=info.filename,
            )
            for _event, element in ET.iterparse(reader, events=("end",)):
                elements += 1
                if elements > int(element_limit):
                    raise ValueError(f"XLSX XML has too many elements: {info.filename}")
                text_bytes += len((element.text or "").encode("utf-8", errors="replace"))
                if text_bytes > int(text_limit):
                    raise ValueError(
                        f"XLSX XML text exceeds the configured limit: {info.filename}"
                    )
                element.clear()
    except (BadZipFile, ET.ParseError, RuntimeError) as exc:
        raise ValueError(f"Invalid XLSX XML member: {info.filename}") from exc


def _parse_xml_root(archive: ZipFile, info: ZipInfo) -> ET.Element:
    _preflight_xml_structure(
        archive,
        info,
        byte_limit=_MAX_METADATA_XML_BYTES,
        element_limit=_MAX_METADATA_XML_ELEMENTS,
        text_limit=_MAX_METADATA_XML_TEXT_BYTES,
    )
    try:
        with archive.open(info, "r") as stream:
            reader = _BoundedXmlReader(
                stream,
                byte_limit=min(int(info.file_size), _MAX_XLSX_MEMBER_BYTES),
                member=info.filename,
            )
            root = ET.parse(reader).getroot()
    except (BadZipFile, ET.ParseError, RuntimeError) as exc:
        raise ValueError(f"Invalid XLSX XML member: {info.filename}") from exc
    return root


def _read_shared_strings(archive: ZipFile, info: ZipInfo | None) -> List[str]:
    if info is None:
        return []
    shared: List[str] = []
    element_count = 0
    total_text = 0
    item_tag = f"{{{_MAIN_NS}}}si"
    text_tag = f"{{{_MAIN_NS}}}t"
    try:
        with archive.open(info, "r") as stream:
            reader = _BoundedXmlReader(
                stream,
                byte_limit=min(int(info.file_size), _MAX_XLSX_MEMBER_BYTES),
                member=info.filename,
            )
            for _event, element in ET.iterparse(reader, events=("end",)):
                element_count += 1
                if element_count > _MAX_XML_ELEMENTS:
                    raise ValueError(
                        f"XLSX XML has too many elements: {info.filename}"
                    )
                if element.tag != item_tag:
                    continue
                value = "".join(
                    node.text or "" for node in element.iter(text_tag)
                )
                encoded = len(value.encode("utf-8", errors="replace"))
                if encoded > _MAX_CELL_TEXT_BYTES:
                    raise ValueError(
                        "XLSX shared string exceeds the configured cell-text limit"
                    )
                total_text += encoded
                if total_text > _MAX_XML_TEXT_BYTES:
                    raise ValueError(
                        "XLSX shared strings exceed the configured text limit"
                    )
                shared.append(value)
                if len(shared) > _MAX_SHARED_STRINGS:
                    raise ValueError("XLSX contains too many shared strings")
                element.clear()
    except (BadZipFile, ET.ParseError, RuntimeError) as exc:
        raise ValueError(f"Invalid XLSX XML member: {info.filename}") from exc
    return shared


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
    match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", str(cell_ref).upper())
    if match is None:
        raise ValueError(f"Invalid Excel cell reference: {cell_ref}")
    letters, row_text = match.groups()
    row_number = int(row_text)
    if row_number > _EXCEL_MAX_ROW:
        raise ValueError(f"Excel row reference exceeds XFD1048576 bounds: {cell_ref}")
    value = 0
    for char in letters:
        value = value * 26 + (ord(char) - ord("A") + 1)
    index = value - 1
    if index > _EXCEL_MAX_COLUMN_INDEX:
        raise ValueError(f"Excel column reference exceeds XFD bounds: {cell_ref}")
    return index


def _worksheet_member(target: str) -> str:
    raw = str(target or "").replace("\\", "/")
    if not raw:
        raise ValueError("XLSX worksheet relationship is missing a target")
    member = posixpath.normpath(raw.lstrip("/"))
    if not member.startswith("xl/"):
        member = posixpath.normpath(f"xl/{member}")
    _safe_member_name(member)
    if not member.startswith("xl/worksheets/") or not member.endswith(".xml"):
        raise ValueError(f"Unexpected XLSX worksheet target: {target}")
    return member


def _parse_sheet_rows(
    archive: ZipFile,
    info: ZipInfo,
    shared: List[str],
) -> List[List[str]]:
    rows: List[List[str]] = []
    element_count = 0
    cell_count = 0
    text_bytes = 0
    row_tag = f"{{{_MAIN_NS}}}row"
    cell_tag = f"{{{_MAIN_NS}}}c"
    value_tag = f"{{{_MAIN_NS}}}v"
    text_tag = f"{{{_MAIN_NS}}}t"
    try:
        with archive.open(info, "r") as stream:
            reader = _BoundedXmlReader(
                stream,
                byte_limit=min(int(info.file_size), _MAX_XLSX_MEMBER_BYTES),
                member=info.filename,
            )
            for _event, element in ET.iterparse(reader, events=("end",)):
                element_count += 1
                if element_count > _MAX_XML_ELEMENTS:
                    raise ValueError(f"XLSX worksheet has too many XML elements: {info.filename}")
                if element.tag != row_tag:
                    continue
                if len(rows) >= _MAX_ROWS_PER_SHEET:
                    raise ValueError(f"XLSX worksheet exceeds the row limit: {info.filename}")
                values: Dict[int, str] = {}
                for cell in element.findall(cell_tag):
                    cell_count += 1
                    if cell_count > _MAX_CELLS_PER_SHEET:
                        raise ValueError(f"XLSX worksheet exceeds the cell limit: {info.filename}")
                    index = _column_index(cell.attrib.get("r", ""))
                    if index >= _MAX_IMPORT_COLUMNS:
                        raise ValueError(
                            f"XLSX teaching-load row exceeds the {_MAX_IMPORT_COLUMNS}-column import limit"
                        )
                    if index in values:
                        raise ValueError(f"XLSX row contains a duplicate cell reference: {cell.attrib.get('r', '')}")
                    cell_type = cell.attrib.get("t", "")
                    raw = cell.find(value_tag)
                    value = "" if raw is None else str(raw.text or "")
                    if cell_type == "s" and value:
                        try:
                            shared_index = int(value)
                        except ValueError as exc:
                            raise ValueError("XLSX shared-string index is not an integer") from exc
                        if shared_index < 0 or shared_index >= len(shared):
                            raise ValueError("XLSX shared-string index is out of range")
                        value = shared[shared_index]
                    elif cell_type == "inlineStr":
                        value = "".join(node.text or "" for node in cell.iter(text_tag))
                    encoded = len(value.encode("utf-8", errors="replace"))
                    if encoded > _MAX_CELL_TEXT_BYTES:
                        raise ValueError("XLSX cell text exceeds the configured limit")
                    text_bytes += encoded
                    if text_bytes > _MAX_XML_TEXT_BYTES:
                        raise ValueError(f"XLSX worksheet text exceeds the configured limit: {info.filename}")
                    values[index] = _clean(value)
                width = max(values.keys(), default=-1) + 1
                rows.append([values.get(index, "") for index in range(width)])
                element.clear()
    except (BadZipFile, ET.ParseError, RuntimeError) as exc:
        raise ValueError(f"Invalid XLSX worksheet XML: {info.filename}") from exc
    return rows


def _xlsx_sheets(path: str | Path) -> Iterable[tuple[str, List[List[str]]]]:
    source = Path(path)
    _preflight_zip_container(source)
    with ZipFile(source) as archive:
        members = _preflight_archive(archive)
        ns = {"m": _MAIN_NS, "r": _REL_NS}
        workbook_info = members.get("xl/workbook.xml")
        relationships_info = members.get("xl/_rels/workbook.xml.rels")
        if workbook_info is None or relationships_info is None:
            raise ValueError("XLSX is missing workbook metadata")
        shared = _read_shared_strings(archive, members.get("xl/sharedStrings.xml"))
        workbook = _parse_xml_root(archive, workbook_info)
        relationships = _parse_xml_root(archive, relationships_info)
        targets: Dict[str, str] = {}
        for node in relationships.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
            rel_id = str(node.attrib.get("Id", ""))
            if not rel_id or rel_id in targets:
                raise ValueError("XLSX contains an invalid or duplicate relationship id")
            if str(node.attrib.get("TargetMode", "")).lower() == "external":
                continue
            targets[rel_id] = str(node.attrib.get("Target", ""))
        sheets_node = workbook.find("m:sheets", ns)
        sheets = list(sheets_node) if sheets_node is not None else []
        if len(sheets) > _MAX_SHEETS:
            raise ValueError("XLSX contains too many worksheets")
        for sheet in sheets:
            name = str(sheet.attrib.get("name", "Sheet"))
            rel_id = sheet.attrib.get(f"{{{_REL_NS}}}id", "")
            if rel_id not in targets:
                raise ValueError(f"XLSX worksheet relationship is missing: {rel_id}")
            member = _worksheet_member(targets[rel_id])
            info = members.get(member)
            if info is None:
                raise ValueError(f"XLSX worksheet member is missing: {member}")
            rows = _parse_sheet_rows(archive, info, shared)
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
