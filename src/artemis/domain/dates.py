"""Date parsing delegated to ``python-dateutil``."""

from __future__ import annotations

from datetime import date

from dateutil import parser as _dtparser


def try_parse_date(value: str | None, *, dayfirst: bool = False) -> date | None:
    """Parse a loose date string, returning ``None`` if it is not a date."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return _dtparser.parse(text, dayfirst=dayfirst).date()
    except (ValueError, OverflowError):
        return None


def parse_date(value: str | date | None, *, dayfirst: bool = False) -> date:
    """Parse a date (or pass a ``date`` through); default to today; else raise."""
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    parsed = try_parse_date(str(value), dayfirst=dayfirst)
    if parsed is None:
        raise ValueError(f"unrecognized date: {value!r}")
    return parsed
