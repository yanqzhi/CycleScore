"""Company domain entity."""

from dataclasses import dataclass
from datetime import datetime

from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class Company:
    """Issuer or operating company master data."""

    name: str
    country_code: str
    id: int | None = None
    fiscal_year_end: str | None = None
    reporting_currency: str | None = None
    listing_status: str = "listed"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise DomainValidationError("Company name must not be empty.")
        if len(self.country_code) != 2 or not self.country_code.isalpha():
            raise DomainValidationError("country_code must be a two-letter code.")
        if self.reporting_currency is not None and len(self.reporting_currency) != 3:
            raise DomainValidationError("reporting_currency must have three letters.")
