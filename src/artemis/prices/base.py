"""Pluggable price sources for the portfolio domain."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class PriceQuote(BaseModel):
    symbol: str
    price_minor: int
    currency: str = "USD"
    as_of: date
    source: str = "manual"


@runtime_checkable
class PriceSource(Protocol):
    name: str

    async def quote(self, symbol: str, currency: str = "USD") -> PriceQuote | None:
        """Return the latest price for ``symbol`` or ``None`` if unavailable."""
        ...


class ManualPriceSource:
    """Price source that never fetches: prices come from stored snapshots."""

    name = "manual"

    async def quote(self, symbol: str, currency: str = "USD") -> PriceQuote | None:
        return None
