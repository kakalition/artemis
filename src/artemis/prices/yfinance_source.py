"""Optional free market-data source backed by ``yfinance``.

``yfinance`` is an optional dependency (``pip install 'artemis[prices]'``). If
it is absent, :func:`yfinance_available` returns ``False`` and the source
degrades to a no-op so the portfolio domain keeps working with manual prices.
"""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import date
from decimal import Decimal

from artemis.domain.money import decimal_to_minor
from artemis.prices.base import PriceQuote


def yfinance_available() -> bool:
    return importlib.util.find_spec("yfinance") is not None


class YFinancePriceSource:
    name = "yfinance"

    def __init__(self, currency: str = "USD") -> None:
        self.currency = currency

    async def quote(self, symbol: str, currency: str = "USD") -> PriceQuote | None:
        if not yfinance_available():
            return None
        return await asyncio.to_thread(self._fetch, symbol, currency)

    def _fetch(self, symbol: str, currency: str) -> PriceQuote | None:
        import yfinance as yf  # local import: optional dependency

        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period="1d")
            if history is None or history.empty:
                return None
            close = history["Close"].iloc[-1]
            price_minor = decimal_to_minor(Decimal(str(close)), currency)
            if price_minor <= 0:
                return None
            return PriceQuote(
                symbol=symbol.upper(),
                price_minor=price_minor,
                currency=currency.upper(),
                as_of=date.today(),
                source=self.name,
            )
        except Exception:
            return None
