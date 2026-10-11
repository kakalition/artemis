"""CSV / bank-statement import.

The **canonical column schema** (case-insensitive; extra columns ignored) is:

===================  ========  =================================================
Column               Required  Aliases
===================  ========  =================================================
``date``             yes       posted_at, transaction_date, posting_date
``amount``           yes*      value, sum
``description``      yes       memo, narrative, details, note
``currency``         no        ccy, currency_code
``merchant``         no        payee, counterparty, name
``external_id``      no        id, transaction_id, reference, ref
``category``         no        category_name, tag
``account``          no        account_name
``debit``/``credit`` no        withdrawal / deposit (used when ``amount`` absent)
===================  ========  =================================================

``*`` ``amount`` may be replaced by a ``debit`` column (money out) and/or a
``credit`` column (money in). Amounts are parsed with
:func:`artemis.domain.money.parse_amount`; no float is ever used.

Parsing never raises on a bad row: problems are collected as warnings and the
good rows are returned.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import date

from artemis.domain.dates import try_parse_date
from artemis.domain.money import parse_amount

_ALIASES: dict[str, set[str]] = {
    "date": {"date", "posted_at", "transaction_date", "posting_date", "date_posted"},
    "amount": {"amount", "value", "sum", "amount_minor"},
    "debit": {"debit", "withdrawal", "money_out", "outflow"},
    "credit": {"credit", "deposit", "money_in", "inflow"},
    "description": {"description", "memo", "narrative", "details", "note"},
    "merchant": {"merchant", "payee", "counterparty", "name"},
    "currency": {"currency", "ccy", "currency_code"},
    "external_id": {"external_id", "id", "transaction_id", "reference", "ref"},
    "category": {"category", "category_name", "tag"},
    "account": {"account", "account_name"},
}

@dataclass(slots=True)
class ParsedRow:
    posted_at: date
    amount_minor: int
    currency: str = "USD"
    description: str = ""
    merchant: str | None = None
    external_id: str | None = None
    category_name: str | None = None
    account_name: str | None = None


@dataclass(slots=True)
class ImportResult:
    rows: list[ParsedRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detected_headers: dict[str, str] = field(default_factory=dict)


def _norm_header(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _resolve_headers(fieldnames: list[str]) -> dict[str, str]:
    by_norm = {_norm_header(h): h for h in fieldnames if h}
    resolved: dict[str, str] = {}
    for canonical, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in by_norm:
                resolved[canonical] = by_norm[alias]
                break
    return resolved


def _derive_external_id(row: ParsedRow, occurrence: int) -> str:
    basis = "|".join(
        [
            row.posted_at.isoformat(),
            str(row.amount_minor),
            (row.description or "").strip().lower(),
            (row.merchant or "").strip().lower(),
            str(occurrence),
        ]
    )
    return "csv:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def parse_csv(
    text: str,
    *,
    default_currency: str = "USD",
    dayfirst: bool = False,
    synthesize_external_ids: bool = False,
) -> ImportResult:
    """Parse CSV text into normalized :class:`ParsedRow` objects."""
    result = ImportResult()
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        result.warnings.append("empty CSV: no header row found")
        return result

    headers = _resolve_headers(list(reader.fieldnames))
    result.detected_headers = headers
    if "date" not in headers:
        result.warnings.append("missing required 'date' column")
        return result
    if "amount" not in headers and "debit" not in headers and "credit" not in headers:
        result.warnings.append("missing an 'amount' column (or debit/credit columns)")
        return result

    occurrence: dict[tuple, int] = {}
    for lineno, raw in enumerate(reader, start=2):
        try:
            row = _parse_row(raw, headers, default_currency, dayfirst)
        except _RowError as exc:
            result.warnings.append(f"line {lineno}: {exc}")
            continue
        if row is None:
            continue
        if row.external_id is None and synthesize_external_ids:
            key = (row.posted_at, row.amount_minor, row.description, row.merchant)
            occurrence[key] = occurrence.get(key, 0) + 1
            row.external_id = _derive_external_id(row, occurrence[key] - 1)
        result.rows.append(row)
    return result


class _RowError(Exception):
    pass


def _get(raw: dict[str, str], headers: dict[str, str], canonical: str) -> str | None:
    header = headers.get(canonical)
    if not header:
        return None
    value = raw.get(header)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_row(
    raw: dict[str, str],
    headers: dict[str, str],
    default_currency: str,
    dayfirst: bool,
) -> ParsedRow | None:
    date_value = _get(raw, headers, "date")
    if not date_value:
        raise _RowError("blank date")
    posted_at = try_parse_date(date_value, dayfirst=dayfirst)
    if posted_at is None:
        raise _RowError(f"unparseable date {date_value!r}")

    currency = (_get(raw, headers, "currency") or default_currency).upper()

    amount_value = _get(raw, headers, "amount")
    try:
        if amount_value is not None:
            amount_minor = parse_amount(amount_value, currency)
        else:
            debit = _get(raw, headers, "debit")
            credit = _get(raw, headers, "credit")
            if debit is None and credit is None:
                return None
            amount_minor = 0
            if debit is not None:
                amount_minor -= abs(parse_amount(debit, currency))
            if credit is not None:
                amount_minor += abs(parse_amount(credit, currency))
    except ValueError as exc:
        raise _RowError(str(exc)) from exc

    description = _get(raw, headers, "description") or ""
    merchant = _get(raw, headers, "merchant")
    return ParsedRow(
        posted_at=posted_at,
        amount_minor=amount_minor,
        currency=currency,
        description=description,
        merchant=merchant,
        external_id=_get(raw, headers, "external_id"),
        category_name=_get(raw, headers, "category"),
        account_name=_get(raw, headers, "account"),
    )
