"""Exchange-specific security listing and lifecycle."""

from dataclasses import dataclass
from datetime import date, datetime

from cyclescope.domain.exceptions import DomainValidationError

LISTING_STATUSES = frozenset({"active", "suspended", "delisted"})


@dataclass(frozen=True, slots=True)
class Listing:
    """A security's exchange listing, with dates preserving its lifecycle."""

    security_id: int
    exchange_id: int
    ticker: str
    trading_currency: str
    listing_date: date
    id: int | None = None
    delisting_date: date | None = None
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.security_id < 1 or self.exchange_id < 1:
            raise DomainValidationError(
                "Listing security and exchange IDs must be positive."
            )
        if not self.ticker.strip() or len(self.trading_currency) != 3:
            raise DomainValidationError(
                "Listing ticker and trading currency are required."
            )
        if self.delisting_date and self.delisting_date < self.listing_date:
            raise DomainValidationError("delisting_date must not precede listing_date.")
        if self.status not in LISTING_STATUSES:
            raise DomainValidationError(
                "Listing status must be active, suspended, or delisted."
            )
        if self.status == "delisted" and self.delisting_date is None:
            raise DomainValidationError(
                "A delisted listing must have a delisting date."
            )
        if self.status != "delisted" and self.delisting_date is not None:
            raise DomainValidationError(
                "Only a delisted listing may have a delisting date."
            )
