"""Daily OHLCV market observation."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.market_data import validate_currency_code


@dataclass(frozen=True, slots=True)
class DailyPrice:
    """One immutable, provenance-preserving daily price revision.

    A zero price is permitted for securities that can legitimately be suspended,
    distressed, or reported with a zero value by a source. It is never treated as
    missing; missing prices must be rejected by the importer.
    """

    security_id: int
    observation_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: int
    currency: str
    source_id: int
    publication_date: date | None
    available_at: datetime
    collected_at: datetime
    revision_number: int
    created_at: datetime
    updated_at: datetime
    id: int | None = None

    def __post_init__(self) -> None:
        if self.security_id < 1 or self.source_id < 1:
            raise DomainValidationError("security_id and source_id must be positive.")
        if isinstance(self.observation_date, datetime) or not isinstance(
            self.observation_date, date
        ):
            raise DomainValidationError("observation_date must be a calendar date.")
        prices: tuple[Decimal, ...] = (self.open, self.high, self.low, self.close)
        if self.adjusted_close is not None:
            prices += (self.adjusted_close,)
        if any(not isinstance(value, Decimal) for value in prices):
            raise DomainValidationError("Prices must use Decimal values.")
        if any(not value.is_finite() or value < 0 for value in prices):
            raise DomainValidationError("Prices must be finite and non-negative.")
        if self.high < max(self.open, self.close, self.low):
            raise DomainValidationError("high must be >= open, close, and low.")
        if self.low > min(self.open, self.close):
            raise DomainValidationError("low must be <= open and close.")
        if self.volume < 0:
            raise DomainValidationError("volume must not be negative.")
        validate_currency_code(self.currency)
        if self.revision_number < 1:
            raise DomainValidationError("revision_number must be positive.")
        for field_name in ("available_at", "collected_at", "created_at", "updated_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise DomainValidationError(f"{field_name} must be timezone-aware.")
            object.__setattr__(self, field_name, value.astimezone(UTC))
