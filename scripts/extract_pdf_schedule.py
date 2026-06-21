from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
SLOTS = [
    ("08:30 - 10:00", 215.0, 292.0, 292.0, 332.0),
    ("10:30 - 12:00", 320.0, 410.0, 410.0, 450.0),
    ("12:15 - 13:45", 438.0, 528.0, 528.0, 568.0),
    ("14:15 - 15:45", 555.0, 646.0, 646.0, 688.0),
    ("16:00 - 17:30", 672.0, 766.0, 766.0, 812.0),
]
MAJOR_RE = re.compile(
    r"^(?:MCTR|CSEN|MGT|BINF|GIU\s+(?:AUTO|ROBO|MANF|BA))\s+\d+(?:st|nd|rd|th)$"
)
ROOM_RE = re.compile(r"^\d+(?:\.\d+)?/?$")


@dataclass(frozen=True)
class Word:
    text: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def x_mid(self) -> float:
        return (self.x_min + self.x_max) / 2.0

    @property
    def y_mid(self) -> float:
        return (self.y_min + self.y_max) / 2.0


@dataclass(frozen=True)
class MajorRow:
    major: str
    y_mid: float


def _run_pdftotext(pdf_path: Path, xhtml_path: Path) -> None:
    subprocess.run(
        ["pdftotext", "-bbox-layout", str(pdf_path), str(xhtml_path)],
        check=True,
    )


def _words_in(node: ET.Element, namespace: str) -> list[Word]:
    words: list[Word] = []
    for word in node.findall(f".//{namespace}word"):
        text = "".join(word.itertext()).strip()
        if not text:
            continue
        words.append(
            Word(
                text=text,
                x_min=float(word.attrib["xMin"]),
                y_min=float(word.attrib["yMin"]),
                x_max=float(word.attrib["xMax"]),
                y_max=float(word.attrib["yMax"]),
            )
        )
    return words


def _line_text(line: ET.Element, namespace: str) -> tuple[str, float, float, float]:
    words = _words_in(line, namespace)
    text = " ".join(word.text for word in sorted(words, key=lambda w: w.x_min)).strip()
    if not words:
        return "", 0.0, 0.0, 0.0
    return (
        text,
        min(word.x_min for word in words),
        max(word.x_max for word in words),
        sum(word.y_mid for word in words) / len(words),
    )


def _extract_week_date(words: Iterable[Word], fallback_week: int) -> tuple[int, str]:
    side_words = [
        word for word in words
        if word.x_mid < 90.0 and 100.0 < word.y_mid < 520.0
    ]
    ordered = " ".join(word.text for word in sorted(side_words, key=lambda w: -w.y_mid))
    match = re.search(r"Week\s+(\d+)\s+([0-9.]+)\s+-\s+([0-9.]+)", ordered)
    if match:
        return int(match.group(1)), f"{match.group(2)} - {match.group(3)}"
    return int(fallback_week), ""


def _extract_day(words: Iterable[Word], fallback_day: str) -> str:
    for word in sorted(words, key=lambda w: (w.y_mid, w.x_mid)):
        if 90.0 <= word.x_mid <= 135.0 and word.text in DAYS:
            return word.text
    return fallback_day


def _extract_major_rows(page: ET.Element, namespace: str) -> list[MajorRow]:
    rows: list[MajorRow] = []
    for line in page.findall(f".//{namespace}line"):
        text, x_min, x_max, y_mid = _line_text(line, namespace)
        if not text or y_mid < 100.0:
            continue
        if 130.0 <= x_min <= 165.0 and x_max <= 225.0 and MAJOR_RE.match(text):
            rows.append(MajorRow(major=text, y_mid=y_mid))
    rows.sort(key=lambda row: row.y_mid)
    return rows


def _text_in_region(
    words: Iterable[Word],
    *,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    room_only: bool = False,
) -> str:
    selected = [
        word for word in words
        if x_min <= word.x_mid < x_max and y_min <= word.y_mid < y_max
    ]
    if room_only:
        selected = [word for word in selected if ROOM_RE.match(word.text)]
    if not selected:
        return ""

    lines: list[list[Word]] = []
    for word in sorted(selected, key=lambda w: (w.y_mid, w.x_mid)):
        for line in lines:
            if abs(line[0].y_mid - word.y_mid) <= 4.0:
                line.append(word)
                break
        else:
            lines.append([word])

    chunks = []
    for line in lines:
        chunks.append(" ".join(word.text for word in sorted(line, key=lambda w: w.x_min)))
    return " ".join(chunk for chunk in chunks if chunk).strip()


def _status_for(course: str) -> str:
    normalized = str(course or "").strip().lower()
    if not normalized:
        return "blank"
    if normalized == "free":
        return "free"
    if normalized == "holiday":
        return "holiday"
    return "scheduled"


def extract(pdf_path: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        xhtml_path = Path(temp_dir) / "schedule.xhtml"
        _run_pdftotext(pdf_path, xhtml_path)
        tree = ET.parse(xhtml_path)

    root = tree.getroot()
    namespace = "{http://www.w3.org/1999/xhtml}"
    pages = root.findall(f".//{namespace}page")
    cells: list[dict[str, object]] = []

    for page_index, page in enumerate(pages):
        words = _words_in(page, namespace)
        fallback_week = page_index // len(DAYS) + 1
        fallback_day = DAYS[page_index % len(DAYS)]
        week, date_range = _extract_week_date(words, fallback_week)
        day = _extract_day(words, fallback_day)
        major_rows = _extract_major_rows(page, namespace)
        if not major_rows:
            continue

        row_centers = [row.y_mid for row in major_rows]
        for row_index, row in enumerate(major_rows):
            top = 100.0 if row_index == 0 else (row_centers[row_index - 1] + row.y_mid) / 2.0
            bottom = (
                float(page.attrib.get("height", 595.2)) - 20.0
                if row_index == len(major_rows) - 1
                else (row.y_mid + row_centers[row_index + 1]) / 2.0
            )
            for slot_index, (slot_label, course_x_min, course_x_max, room_x_min, room_x_max) in enumerate(SLOTS, start=1):
                course = _text_in_region(
                    words,
                    x_min=course_x_min,
                    x_max=course_x_max,
                    y_min=top,
                    y_max=bottom,
                )
                room = _text_in_region(
                    words,
                    x_min=room_x_min,
                    x_max=room_x_max,
                    y_min=top,
                    y_max=bottom,
                    room_only=True,
                )
                cells.append(
                    {
                        "source_page": int(page_index + 1),
                        "week": int(week),
                        "date_range": date_range,
                        "day": day,
                        "major": row.major,
                        "major_row_index": int(row_index + 1),
                        "slot_index": int(slot_index),
                        "time": slot_label,
                        "course": course,
                        "room": room,
                        "status": _status_for(course),
                    }
                )

    scheduled = [cell for cell in cells if cell["status"] == "scheduled"]
    summary = {
        "source": str(pdf_path),
        "pages": len(pages),
        "cells": len(cells),
        "scheduled_cells": len(scheduled),
        "free_cells": sum(1 for cell in cells if cell["status"] == "free"),
        "holiday_cells": sum(1 for cell in cells if cell["status"] == "holiday"),
        "blank_cells": sum(1 for cell in cells if cell["status"] == "blank"),
        "weeks": sorted({int(cell["week"]) for cell in cells}),
        "days": sorted({str(cell["day"]) for cell in cells}, key=lambda d: DAYS.index(d) if d in DAYS else 999),
        "majors": sorted({str(cell["major"]) for cell in cells}),
    }
    return cells, summary


def validate(cells: list[dict[str, object]], summary: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if int(summary.get("pages", 0)) != 72:
        errors.append(f"expected 72 pages, got {summary.get('pages')}")
    weeks = set(summary.get("weeks", []))
    if weeks != set(range(1, 13)):
        errors.append(f"expected weeks 1..12, got {sorted(weeks)}")
    days = set(summary.get("days", []))
    if days != set(DAYS):
        errors.append(f"expected Monday-Saturday, got {sorted(days)}")
    for idx, cell in enumerate(cells, start=1):
        if int(cell["slot_index"]) not in range(1, 6):
            errors.append(f"row {idx}: invalid slot {cell['slot_index']}")
        if str(cell["day"]) not in DAYS:
            errors.append(f"row {idx}: invalid day {cell['day']}")
        if int(cell["week"]) not in range(1, 13):
            errors.append(f"row {idx}: invalid week {cell['week']}")
        if cell["status"] == "scheduled" and not str(cell["course"]).strip():
            errors.append(f"row {idx}: scheduled cell has no course text")
    return errors


def write_outputs(cells: list[dict[str, object]], summary: dict[str, object], output_prefix: Path) -> tuple[Path, Path, Path]:
    cells_path = output_prefix.with_name(output_prefix.name + "-cells.csv")
    events_path = output_prefix.with_name(output_prefix.name + "-events.csv")
    summary_path = output_prefix.with_name(output_prefix.name + "-summary.json")
    fieldnames = [
        "source_page",
        "week",
        "date_range",
        "day",
        "major",
        "major_row_index",
        "slot_index",
        "time",
        "course",
        "room",
        "status",
    ]
    with cells_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cells)
    with events_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cell for cell in cells if cell["status"] == "scheduled")
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return cells_path, events_path, summary_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract the SS23 all-majors timetable PDF into CSV.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    output_prefix = args.output_prefix or args.pdf.with_suffix("")
    cells, summary = extract(args.pdf)
    errors = validate(cells, summary)
    if args.check and errors:
        for error in errors:
            print(error)
        return 1
    cells_path, events_path, summary_path = write_outputs(cells, summary, output_prefix)
    print(f"cells: {cells_path}")
    print(f"events: {events_path}")
    print(f"summary: {summary_path}")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
