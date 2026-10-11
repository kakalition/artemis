from datetime import date

from artemis.prices.base import ManualPriceSource, PriceQuote, PriceSource
from artemis.prices.yfinance_source import YFinancePriceSource, yfinance_available


async def test_manual_source_returns_none():
    source = ManualPriceSource()
    assert isinstance(source, PriceSource)
    assert await source.quote("AAPL") is None


def test_yfinance_availability_is_bool():
    assert isinstance(yfinance_available(), bool)


async def test_yfinance_source_noop_when_unavailable():
    source = YFinancePriceSource()
    if yfinance_available():
        return  # network-dependent; only assert the unavailable path
    assert await source.quote("AAPL") is None


def test_price_quote_model():
    quote = PriceQuote(symbol="AAPL", price_minor=15000, as_of=date(2026, 1, 2))
    assert quote.currency == "USD"
    assert quote.source == "manual"
