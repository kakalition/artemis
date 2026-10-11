"""Money helpers.

Rules enforced throughout Artemis:

* Every monetary value is an integer number of **minor units** (cents) plus an
  ISO-4217 currency code.
* ``float`` is never used on a monetary path. Parsing goes ``str -> Decimal ->
  int``; formatting goes ``int -> Decimal -> str``.
* Currency precision and display formatting come from **Babel** (CLDR) rather
  than a hand-maintained table.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from babel.core import get_global
from babel.numbers import format_currency, format_decimal

# CLDR currency fractions: currency -> (digits, rounding, cash_digits, ...).
_CURRENCY_FRACTIONS: Mapping[str, tuple] = get_global("currency_fractions")
_KNOWN_CURRENCIES: set[str] = set(get_global("all_currencies") or ())
_DEFAULT_FRACTION = (2, 0, 2, 0)
_LOCALE = "en_US"

_CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
}

_STRIP_RE = re.compile(r"[\s,\u00a0]")
_ISO_RE = re.compile(r"^[A-Za-z]{3}$")


def minor_exponent(currency: str) -> int:
    """Number of minor units per major unit, per CLDR (default 2)."""
    return _CURRENCY_FRACTIONS.get(currency.upper(), _DEFAULT_FRACTION)[0]


def _to_decimal(value: Decimal | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # guard: bool is an int subclass
        raise TypeError("bool is not a valid monetary amount")
    if isinstance(value, (int, str)):
        return Decimal(value)
    raise TypeError(f"unsupported amount type: {type(value)!r}")


def decimal_to_minor(value: Decimal | int | str, currency: str = "USD") -> int:
    """Convert a major-unit amount to integer minor units (banker's rounding)."""
    dec = _to_decimal(value)
    scaled = dec.scaleb(minor_exponent(currency))
    return int(scaled.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def minor_to_decimal(minor: int, currency: str = "USD") -> Decimal:
    """Convert integer minor units to a major-unit :class:`Decimal`."""
    exponent = minor_exponent(currency)
    return (Decimal(minor) / (Decimal(10) ** exponent)).quantize(Decimal(1).scaleb(-exponent))


def parse_amount(text: str, currency: str = "USD") -> int:
    """Parse a human/LLM amount string into integer minor units.

    Handles ``$42.50``, ``42.5``, ``1,234.56``, ``(42.00)`` (accounting
    negative), ``-42``, ``42 USD`` and ``USD 42``. Raises :class:`ValueError`
    on anything it cannot interpret as a single amount.
    """
    if text is None:
        raise ValueError("cannot parse amount from None")
    raw = str(text).strip()
    if not raw:
        raise ValueError("cannot parse amount from empty string")

    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative = True
        raw = raw[1:-1]

    code_match = re.search(r"\b([A-Za-z]{3})\b", raw)
    if code_match and _ISO_RE.match(code_match.group(1)):
        currency = code_match.group(1).upper()
        raw = raw[: code_match.start()] + raw[code_match.end() :]

    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in raw:
            currency = code
            raw = raw.replace(symbol, "")

    raw = _STRIP_RE.sub("", raw)
    if raw.startswith("+"):
        raw = raw[1:]
    elif raw.startswith("-"):
        negative = not negative
        raw = raw[1:]

    if not raw or not re.fullmatch(r"\d+(\.\d+)?", raw):
        raise ValueError(f"cannot parse amount from {text!r}")

    try:
        dec = Decimal(raw)
    except InvalidOperation as exc:  # pragma: no cover - guarded by regex
        raise ValueError(f"cannot parse amount from {text!r}") from exc

    minor = decimal_to_minor(dec, currency)
    return -minor if negative else minor


def format_minor(minor: int, currency: str = "USD", *, with_symbol: bool = True) -> str:
    """Format integer minor units for display, using Babel/CLDR."""
    currency = currency.upper()
    exponent = minor_exponent(currency)
    value = minor_to_decimal(minor, currency)
    if with_symbol and currency in _KNOWN_CURRENCIES:
        return format_currency(value, currency, locale=_LOCALE)
    pattern = "#,##0." + "0" * exponent if exponent else "#,##0"
    return f"{format_decimal(value, format=pattern, locale=_LOCALE)} {currency}"
