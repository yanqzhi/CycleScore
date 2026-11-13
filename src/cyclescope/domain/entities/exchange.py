"""Exchange reference data using stable exchange codes."""

from dataclasses import dataclass
from datetime import datetime

from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class Exchange:
    """A market venue independent of any issuer ticker symbol."""

    exchange_code: str
    exchange_name: str
    country_code: str
    market_region: str
    timezone: str
    currency_code: str
    exchange_id: int | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def id(self) -> int | None:
        """Expose the local exchange key to generic repository contracts."""
        return self.exchange_id

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.exchange_code,
                self.exchange_name,
                self.country_code,
                self.market_region,
                self.timezone,
                self.currency_code,
            )
        ):
            raise DomainValidationError("Exchange reference fields are required.")
        if len(self.country_code) != 2 or len(self.currency_code) != 3:
            raise DomainValidationError(
                "Country and currency codes have invalid length."
            )
