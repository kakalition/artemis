import pytest

from artemis.agents.deps import Deps
from artemis.config import Settings
from artemis.prices.base import ManualPriceSource
from artemis.services import ledger


def _deps(repos, **overrides) -> Deps:
    return Deps(
        owner_id="owner",
        repos=repos,
        settings=Settings(owner_id="owner", **overrides),
        price_source=ManualPriceSource(),
    )


def test_csv_size_cap_raises(repos):
    deps = _deps(repos, max_import_bytes=10)
    with pytest.raises(ValueError, match="too large"):
        ledger.import_csv(deps, text="date,amount,description\n" + "x" * 200)


def test_csv_within_cap_ok(repos):
    deps = _deps(repos, max_import_bytes=10_000)
    summary = ledger.import_csv(deps, text="date,amount,description\n2026-01-05,-10.00,Coffee\n")
    assert summary.inserted == 1
