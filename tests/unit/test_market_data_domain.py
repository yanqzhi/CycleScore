"""Domain validation for market-data entities and value objects."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from cyclescope.domain.entities import DailyPrice, FxRate
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.market_data import CurrencyPair, MarketDataPeriod

NOW = datetime(2024, 1, 3, 12, tzinfo=UTC)


def price(**overrides: object) -> DailyPrice:
    """Create a valid observation, permitting focused field overrides."""
    values: dict[str, object] = {
        "security_id": 1,
        "observation_date": date(2024, 1, 2),
        "open": Decimal("10"),
        "high": Decimal("12"),
        "low": Decimal("9"),
        "close": Decimal("11"),
        "adjusted_close": None,
        "volume": 100,
        "currency": "USD",
        "source_id": 1,
        "publication_date": date(2024, 1, 2),
        "available_at": NOW,
        "collected_at": NOW,
        "revision_number": 1,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return DailyPrice(**values)  # type: ignore[arg-type]


def test_daily_price_accepts_zero_price_and_normalizes_utc() -> None:
    record = price(open=Decimal("0"), low=Decimal("0"), close=Decimal("0"))
    assert record.open == Decimal("0")
    assert record.available_at.utcoffset() == UTC.utcoffset(NOW)


@pytest.mark.parametrize(
    "overrides",
    [
        {"open": Decimal("-1")},
        {"high": Decimal("9")},
        {"low": Decimal("11")},
        {"volume": -1},
        {"currency": "usd"},
        {"revision_number": 0},
        {"available_at": datetime(2024, 1, 3)},
        {"observation_date": datetime(2024, 1, 2)},
        {"close": 11.0},
    ],
)
def test_daily_price_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(DomainValidationError):
        price(**overrides)


def test_fx_rate_validates_pair_rate_and_timestamps() -> None:
    rate = FxRate(
        base_currency="USD",
        quote_currency="JPY",
        observation_date=date(2024, 1, 2),
        rate=Decimal("145.25"),
        source_id=1,
        publication_date=None,
        available_at=NOW,
        collected_at=NOW,
        revision_number=1,
    )
    assert rate.rate == Decimal("145.25")
    for fields in (
        {"base_currency": "USD", "quote_currency": "USD", "rate": Decimal("1")},
        {"base_currency": "usd", "quote_currency": "JPY", "rate": Decimal("1")},
        {"base_currency": "USD", "quote_currency": "JPY", "rate": Decimal("0")},
        {"base_currency": "USD", "quote_currency": "JPY", "rate": Decimal("NaN")},
    ):
        with pytest.raises(DomainValidationError):
            FxRate(
                base_currency=fields["base_currency"],  # type: ignore[arg-type]
                quote_currency=fields["quote_currency"],  # type: ignore[arg-type]
                observation_date=date(2024, 1, 2),
                rate=fields["rate"],  # type: ignore[arg-type]
                source_id=1,
                publication_date=None,
                available_at=NOW,
                collected_at=NOW,
                revision_number=1,
            )


def test_currency_pair_and_market_period_validate() -> None:
    assert CurrencyPair("USD", "JPY").quote_currency == "JPY"
    with pytest.raises(DomainValidationError):
        CurrencyPair("USD", "USD")
    with pytest.raises(DomainValidationError):
        CurrencyPair("US", "JPY")
    with pytest.raises(DomainValidationError):
        MarketDataPeriod(date(2024, 2, 1), date(2024, 1, 1))
