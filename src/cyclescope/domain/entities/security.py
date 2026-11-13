"""Security domain entity."""

from dataclasses import dataclass
from datetime import date, datetime

from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class Security:
    """Tradable security listing."""

    company_id: int
    ticker: str
    exchange: str
    currency: str
    security_type: str
    id: int | None = None
    listing_date: date | None = None
    delisting_date: date | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.company_id < 1:
            raise DomainValidationError("company_id must be a positive integer.")
        if not all(
            (self.ticker.strip(), self.exchange.strip(), self.security_type.strip())
        ):
            raise DomainValidationError(
                "Ticker, exchange, and security type are required."
            )
        if len(self.currency) != 3:
            raise DomainValidationError("currency must have three letters.")
