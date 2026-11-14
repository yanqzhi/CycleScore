"""Typed market-data context required to validate CSV rows into Domain entities."""

from dataclasses import dataclass
from datetime import UTC, datetime

from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.market_data import (
    CurrencyPair,
    validate_currency_code,
)

PRICES_DAILY_DATASET = "prices.daily"
FX_DAILY_DATASET = "fx.daily"


def _utc(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class DailyPriceIngestionContext:
    security_id: int
    currency: str
    source_id: int
    available_at: datetime
    collected_at: datetime
    revision_number: int

    def __post_init__(self) -> None:
        if self.security_id < 1 or self.source_id < 1 or self.revision_number < 1:
            raise DomainValidationError(
                "Price context IDs and revision must be positive."
            )
        currency = self.currency.strip().upper()
        validate_currency_code(currency)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(
            self, "available_at", _utc("available_at", self.available_at)
        )
        object.__setattr__(
            self, "collected_at", _utc("collected_at", self.collected_at)
        )


@dataclass(frozen=True, slots=True)
class FxRateIngestionContext:
    base_currency: str
    quote_currency: str
    source_id: int
    available_at: datetime
    collected_at: datetime
    revision_number: int

    def __post_init__(self) -> None:
        if self.source_id < 1 or self.revision_number < 1:
            raise DomainValidationError(
                "FX context source and revision must be positive."
            )
        pair = CurrencyPair(
            self.base_currency.strip().upper(), self.quote_currency.strip().upper()
        )
        object.__setattr__(self, "base_currency", pair.base_currency)
        object.__setattr__(self, "quote_currency", pair.quote_currency)
        object.__setattr__(
            self, "available_at", _utc("available_at", self.available_at)
        )
        object.__setattr__(
            self, "collected_at", _utc("collected_at", self.collected_at)
        )
