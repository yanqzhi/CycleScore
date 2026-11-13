"""Point-in-time foreign exchange observation."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.market_data import CurrencyPair


@dataclass(frozen=True, slots=True)
class FxRate:
    """A rate quoted as units of quote currency per one base currency."""

    base_currency: str
    quote_currency: str
    observation_date: date
    rate: Decimal
    source_id: int
    publication_date: date | None
    available_at: datetime
    collected_at: datetime
    revision_number: int
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        CurrencyPair(self.base_currency, self.quote_currency)
        if isinstance(self.observation_date, datetime) or not isinstance(
            self.observation_date, date
        ):
            raise DomainValidationError("observation_date must be a calendar date.")
        if (
            not isinstance(self.rate, Decimal)
            or not self.rate.is_finite()
            or self.rate <= 0
        ):
            raise DomainValidationError("rate must be a finite positive Decimal.")
        if self.source_id < 1 or self.revision_number < 1:
            raise DomainValidationError(
                "source_id and revision_number must be positive."
            )
        for field_name in ("available_at", "collected_at", "created_at", "updated_at"):
            value = getattr(self, field_name)
            if value is not None:
                if value.tzinfo is None or value.utcoffset() is None:
                    raise DomainValidationError(f"{field_name} must be timezone-aware.")
                object.__setattr__(self, field_name, value.astimezone(UTC))
