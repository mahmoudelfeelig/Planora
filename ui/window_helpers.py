from __future__ import annotations

from ui.window_runtime import *  # noqa: F401,F403


class WindowHelpersMixin:

    @staticmethod
    def _infer_room_category(capacity: int) -> str:
        if capacity <= 80:
            return "SMALL"
        if capacity <= 180:
            return "MEDIUM"
        return "BIG"

    @staticmethod
    def _make_locked_item(
        text: str, *, numeric: bool = False, natural: bool = False
    ) -> QTableWidgetItem:
        if numeric:
            item: QTableWidgetItem = NumericTableItem(text)
        elif natural:
            item = NaturalSortTableItem(text)
        else:
            item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    @staticmethod
    def _make_numeric_item(value: Any) -> QTableWidgetItem:
        return NumericTableItem(str(value))

    @staticmethod
    def _parse_csv_ints(raw: str) -> List[int]:
        out: List[int] = []
        for token in str(raw).split(","):
            token = token.strip()
            if not token:
                continue
            try:
                out.append(int(token))
            except Exception:
                continue
        return out

    @staticmethod
    def _parse_csv_days(raw: str) -> List[str]:
        valid = {"MON", "TUE", "WED", "THU", "FRI", "SAT"}
        out: List[str] = []
        for token in str(raw).split(","):
            day = token.strip().upper()
            if day in valid:
                out.append(day)
        return out

    @staticmethod
    def _parse_csv_weeks(raw: str) -> List[int]:
        text = str(raw).strip()
        if not text or text.upper() == "ALL":
            return []
        out: List[int] = []
        for token in text.split(","):
            token = token.strip()
            if not token:
                continue
            if "-" in token:
                parts = token.split("-", 1)
                try:
                    start = int(parts[0].strip())
                    end = int(parts[1].strip())
                except Exception:
                    continue
                lo = min(start, end)
                hi = max(start, end)
                out.extend(range(int(lo), int(hi) + 1))
                continue
            try:
                out.append(int(token))
            except Exception:
                continue
        return sorted(set(out))

    @staticmethod
    def _parse_csv_names(raw: str) -> List[str]:
        out: List[str] = []
        for token in str(raw).split(","):
            name = token.strip()
            if name:
                out.append(name)
        return out

    @staticmethod
    def _parse_term_blocks(raw: str) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        for idx, token in enumerate(str(raw).split(","), start=1):
            part = token.strip()
            if not part:
                continue
            if ":" in part:
                label, length_text = part.split(":", 1)
            else:
                label, length_text = f"Term {idx}", part
            label = str(label).strip() or f"Term {idx}"
            teaching = True
            if label.startswith("!"):
                label = label[1:].strip() or f"Term {idx}"
                teaching = False
            try:
                length = max(1, int(str(length_text).strip()))
            except Exception:
                continue
            blocks.append(
                {
                    "label": str(label),
                    "length_weeks": int(length),
                    "teaching": bool(teaching),
                }
            )
        return blocks

    @staticmethod
    def _format_term_blocks(blocks: List[Dict[str, Any]] | None) -> str:
        parts: List[str] = []
        for idx, block in enumerate(blocks or [], start=1):
            if not isinstance(block, dict):
                continue
            try:
                length = max(1, int(block.get("length_weeks", 0)))
            except Exception:
                continue
            label = str(block.get("label", f"Term {idx}") or f"Term {idx}").strip()
            teaching = bool(block.get("teaching", True))
            if not teaching:
                label = "!" + label
            parts.append(f"{label}:{length}")
        return ", ".join(parts)

    @staticmethod
    def _compact_status_text(text: str) -> str:
        full = str(text or "")
        match = re.match(
            r"^Improving\.\.\. (\d+)% \(iter (\d+)/(\d+), "
            r"(?:original=(\d+), )?current=(\d+), best=(\d+)\)$",
            full,
        )
        if not match:
            return full
        pct, done, total, original, current, best = match.groups()
        if original is None:
            return f"Improving {pct}% | {done}/{total} | current {current} | best {best}"
        return f"Improving {pct}% | {done}/{total} | {original}->{current} | best {best}"

    @staticmethod
    def _focus_label(term: str) -> str:
        return str(term or "overall").replace("_", " ")

    @staticmethod
    def _describe_penalty_delta(delta: int) -> str:
        if int(delta) < 0:
            return f"gain {abs(int(delta))}"
        if int(delta) > 0:
            return f"loss {int(delta)}"
        return "no change"

    @staticmethod
    def _format_json_debug(value: Any, *, max_chars: int = 12000) -> str:
        try:
            text = json.dumps(value, indent=2, sort_keys=True, default=str)
        except Exception:
            text = str(value)
        if len(text) > int(max_chars):
            return text[: int(max_chars)] + "\n... truncated ..."
        return text

    @staticmethod
    def _top_counts(values: Dict[int, int], limit: int = 3) -> list[tuple[int, int]]:
        items = [(int(k), int(v)) for k, v in values.items()]
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        return items[:limit]

    @staticmethod
    def _split_phased_budget(total_seconds: float) -> tuple[float, float]:
        """
        Split solve budget for phased mode.
        Prioritize feasibility first, then reserve a smaller tail for iterative improvement.
        """
        if total_seconds <= 0:
            return 30.0, 0.0
        if total_seconds <= 60:
            return float(total_seconds), 0.0
        improve = min(90.0, float(total_seconds) * 0.20)
        feasibility = max(30.0, float(total_seconds) - improve)
        return feasibility, max(0.0, float(total_seconds) - feasibility)
