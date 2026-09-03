from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


_FORMULA_PREFIXES = ("=", "+", "-", "@")
_LEADING_WHITESPACE = " \t\r\n\v\f"


def spreadsheet_safe_cell(value: Any) -> Any:
    """Return a CSV cell that spreadsheet applications will not execute.

    Numeric values retain their native type. Text whose first non-whitespace
    character is a spreadsheet formula trigger is prefixed with an apostrophe,
    which makes Excel-compatible readers treat the entire cell as literal text.
    """

    if not isinstance(value, str):
        return value
    candidate = value.lstrip(_LEADING_WHITESPACE)
    if candidate.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def spreadsheet_safe_row(values: Iterable[Any]) -> list[Any]:
    return [spreadsheet_safe_cell(value) for value in values]


def spreadsheet_safe_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): spreadsheet_safe_cell(value) for key, value in values.items()}


__all__ = [
    "spreadsheet_safe_cell",
    "spreadsheet_safe_mapping",
    "spreadsheet_safe_row",
]
